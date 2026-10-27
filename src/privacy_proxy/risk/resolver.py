"""Deterministic overlap resolution for canonical L3/L4 detections."""

import re
from itertools import groupby

from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class
from privacy_proxy.schemas import DetectedPII, DetectionTier

_TIER_RANK = {
    DetectionTier.DETERMINISTIC: 4,
    DetectionTier.RULE_ANCHORED: 3,
    DetectionTier.MODEL: 2,
    DetectionTier.CANDIDATE: 1,
}

_PROTECTION_RANK = {
    PrivacyClass.DIRECT: 4,
    PrivacyClass.SERVICE: 4,
    PrivacyClass.SENSITIVE: 3,
    PrivacyClass.QI: 2,
    PrivacyClass.GENERAL: 1,
}


def _overlaps(left: DetectedPII, right: DetectedPII) -> bool:
    return (
        left.segment_id == right.segment_id
        and left.start_idx < right.end_idx
        and right.start_idx < left.end_idx
    )


def _group(entity: DetectedPII) -> tuple[str, str, DetectionTier]:
    return entity.source, str(entity.entity_type), entity.tier


_MAX_DIRECT_ANCHOR_GAP = 6
_LICENSE_COMPETITORS = {"ORDER_ID", "TRACKING_NUMBER", "CUSTOMER_ID", "ACCOUNT_NUMBER"}
# A label and a value may be separated by horizontal whitespace, one particle,
# and label punctuation. Sentences, newlines and arbitrary words are not links.
_LEFT_LINK = re.compile(r"[ \t]*(?:은|는|이|가|의)?[ \t]*[:\uFF1A=]?[ \t]*")
_RIGHT_LINK = re.compile(r"[ \t]*(?:은|는|이|가)?[ \t]*")


def has_direct_anchor(entity: DetectedPII, raw_prompt: str | None) -> bool:
    """Validate supplied global evidence and the actual intervening text."""
    if raw_prompt is None or entity.anchor_start is None or entity.anchor_end is None:
        return False
    if raw_prompt[entity.anchor_start : entity.anchor_end] != entity.anchor_text:
        return False
    if raw_prompt[entity.start_idx : entity.end_idx] != entity.original_value:
        return False
    if entity.anchor_end <= entity.start_idx:
        gap = raw_prompt[entity.anchor_end : entity.start_idx]
        pattern = _LEFT_LINK
    elif entity.end_idx <= entity.anchor_start:
        gap = raw_prompt[entity.end_idx : entity.anchor_start]
        pattern = _RIGHT_LINK
    else:
        return False
    return len(gap) <= _MAX_DIRECT_ANCHOR_GAP and pattern.fullmatch(gap) is not None


def resolve_overlaps(
    entities: list[DetectedPII], *, raw_prompt: str | None = None
) -> list[DetectedPII]:
    """Tier-first resolution; reject lost coverage or weaker protection.

    Confidence is compared only within one explicit producer/type/tier group,
    when every value in that group is measured. Group keys precede confidence
    to keep sorting transitive and independent of input order.

    raw_prompt is the full original text in the entities' global coordinate
    system. A directly anchored L4 number can outrank a same-span license
    detection. Missing or indirect evidence preserves tier-first resolution.
    Direct anchor evidence precedes confidence within a producer/type group.
    Otherwise indistinguishable candidates with uncomparable, conflicting
    confidence fail closed; producer scores are never rewritten.
    """
    comparable = {
        _group(entity) for entity in entities if entity.source and entity.source != "unknown"
    }
    comparable -= {_group(entity) for entity in entities if entity.confidence is None}

    def priority(
        entity: DetectedPII,
    ) -> tuple[int, int, int, str, str, bool, float, int, str, str, str, int, int]:
        confidence_rank = 0.0
        if _group(entity) in comparable and entity.confidence is not None:
            confidence_rank = entity.confidence
        return (
            _TIER_RANK[entity.tier],
            _PROTECTION_RANK[privacy_class(entity)],
            entity.end_idx - entity.start_idx,
            str(entity.entity_type),
            entity.source,
            has_direct_anchor(entity, raw_prompt),
            confidence_rank,
            -entity.start_idx,
            entity.normalized,
            entity.original_value,
            entity.anchor_text or "",
            entity.anchor_start if entity.anchor_start is not None else -1,
            entity.anchor_end if entity.anchor_end is not None else -1,
        )

    def span(entity: DetectedPII) -> tuple[str, int, int]:
        return entity.segment_id, entity.start_idx, entity.end_idx

    def direct_number(entity: DetectedPII) -> bool:
        return (
            entity.entity_type in _LICENSE_COMPETITORS
            and entity.source.startswith("L4_")
            and entity.tier == DetectionTier.RULE_ANCHORED
            and has_direct_anchor(entity, raw_prompt)
        )

    license_spans = {
        span(entity) for entity in entities if entity.entity_type == "KR_DRIVER_LICENSE"
    }
    exception_spans = {span(entity) for entity in entities if direct_number(entity)} & license_spans
    # Keep the evidence that justified the exception, not just its coordinates.
    # Unrelated deterministic detections still compete at their original tier.
    candidates = [
        entity
        for entity in entities
        if not (
            span(entity) in exception_spans
            and (
                entity.entity_type == "KR_DRIVER_LICENSE"
                or (
                    entity.entity_type in _LICENSE_COMPETITORS
                    and _TIER_RANK[entity.tier] <= _TIER_RANK[DetectionTier.RULE_ANCHORED]
                    and not direct_number(entity)
                )
            )
        )
    ]
    winners: list[DetectedPII] = []
    for _, tied in groupby(sorted(candidates, key=priority, reverse=True), key=priority):
        # Equal explicit keys may still differ in uncomparable confidence.
        # Do not silently pick by input order, synthesize a score or serialize
        # the whole model back into the ranking. Fail only for surviving ties.
        by_segment: dict[str, list[DetectedPII]] = {}
        for candidate in tied:
            by_segment.setdefault(candidate.segment_id, []).append(candidate)
        for segment_id in sorted(by_segment):
            duplicates = by_segment[segment_id]
            candidate = duplicates[0]
            if any(_overlaps(winner, candidate) for winner in winners):
                continue
            if any(item.confidence != candidate.confidence for item in duplicates[1:]):
                raise ValueError("overlap resolution has ambiguous uncomparable confidence")
            winners.append(candidate)

    # A losing span must be fully covered by winners with at least its protection.
    # Never enlarge a winner or invent a new entity type to conceal a conflict.
    for entity in entities:
        cursor = entity.start_idx
        for winner in sorted(winners, key=lambda item: item.start_idx):
            if winner.segment_id != entity.segment_id or winner.end_idx <= cursor:
                continue
            if winner.start_idx > cursor:
                break
            if _PROTECTION_RANK[privacy_class(winner)] < _PROTECTION_RANK[privacy_class(entity)]:
                continue
            cursor = max(cursor, winner.end_idx)
            if cursor >= entity.end_idx:
                break
        if cursor < entity.end_idx:
            raise ValueError("overlap resolution would lose protected coverage")

    return sorted(
        winners,
        key=lambda entity: (entity.segment_id, entity.start_idx, entity.end_idx),
    )
