"""Semantic de-duplication and QI combination bonuses for L5."""

from collections.abc import Iterable

from privacy_proxy.risk.quasi_identifiers import QIFeature, to_qi_feature
from privacy_proxy.schemas import DetectedPII


def select_representative_qis(entities: Iterable[DetectedPII]) -> list[QIFeature]:
    """Remove exact semantic duplicates and keep the most specific version.

    Different location strings remain separate until a location normalizer verifies
    that they belong to the same administrative hierarchy. This avoids treating an
    unrelated pair such as Seoul and Yeongtong-gu as one location.
    """
    representatives: dict[str, QIFeature] = {}
    for entity in entities:
        feature = to_qi_feature(entity)
        if feature is None:
            continue
        current = representatives.get(feature.deduplication_key)
        if current is None or (feature.specificity, feature.base_score) > (
            current.specificity,
            current.base_score,
        ):
            representatives[feature.deduplication_key] = feature
    return list(representatives.values())


def combination_score(features: Iterable[QIFeature]) -> tuple[float, list[str]]:
    """Return bonuses for QI count and high-risk interactions."""
    selected = list(features)
    combination_count = len(selected)
    bonus = 0.0
    reasons: list[str] = []

    if combination_count == 2:
        bonus += 8.0
        reasons.append("서로 다른 준식별자 2개가 결합됨")
    elif combination_count >= 3:
        bonus += 12.0 + 4.0 * (combination_count - 3)
        reasons.append(f"서로 다른 준식별자 {combination_count}개가 결합됨")

    return bonus, reasons
