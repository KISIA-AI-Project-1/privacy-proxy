"""Deterministic overlap resolution for canonical L3/L4 detections."""

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


def resolve_overlaps(
    entities: list[DetectedPII], *, raw_prompt: str | None = None
) -> list[DetectedPII]:
    """Tier-first resolution; reject lost coverage or weaker protection.

    Confidence is compared only within one explicit producer/type/tier group,
    when every value in that group is measured. Group keys precede confidence
    to keep sorting transitive and independent of input order.

    raw_prompt is the full original text in the entities' global coordinate
    system, reserved for anchor context checks once L4 evidence is available.
    Omitting it preserves compatibility with existing standalone callers.
    Resolution currently remains tier-first with or without this text.
    """
    comparable = {
        _group(entity) for entity in entities if entity.source and entity.source != "unknown"
    }
    comparable -= {_group(entity) for entity in entities if entity.confidence is None}

    def priority(entity: DetectedPII) -> tuple[int, int, int, str, str, float, int, str, str]:
        confidence_rank = 0.0
        if _group(entity) in comparable and entity.confidence is not None:
            confidence_rank = entity.confidence
        return (
            _TIER_RANK[entity.tier],
            _PROTECTION_RANK[privacy_class(entity)],
            entity.end_idx - entity.start_idx,
            str(entity.entity_type),
            entity.source,
            confidence_rank,
            -entity.start_idx,
            entity.normalized,
            entity.model_dump_json(),
        )

    winners: list[DetectedPII] = []
    for candidate in sorted(entities, key=priority, reverse=True):
        if not any(_overlaps(winner, candidate) for winner in winners):
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
