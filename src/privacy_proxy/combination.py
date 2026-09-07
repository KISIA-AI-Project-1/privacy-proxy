"""Semantic de-duplication and QI combination bonuses for L5."""

from collections.abc import Iterable

from privacy_proxy.models import DetectedPII
from privacy_proxy.risk.quasi_identifiers import QIFeature, to_qi_feature


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
    """Return bonuses for QI count, rarity, and high-risk interactions."""
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

    has_exact_age = any(feature.exact_age for feature in selected)
    has_detailed_location = any(feature.detailed_location for feature in selected)
    has_rare_product = any(feature.rare for feature in selected)
    has_time = any(feature.category == "TIME" for feature in selected)

    if has_exact_age and has_detailed_location:
        bonus += 17.0
        reasons.append("정확한 연령과 세부 지역의 결합으로 재식별 가능성이 증가함")
    if has_time and has_detailed_location:
        bonus += 8.0
        reasons.append("정확한 시각과 세부 지역이 결합됨")
    if has_rare_product and has_detailed_location:
        reasons.append("희귀 상품과 세부 지역이 결합됨")

    return bonus, reasons
