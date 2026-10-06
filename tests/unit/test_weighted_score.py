import pytest

from privacy_proxy.risk.weighted_score import calculate_weighted_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier


def detection(
    entity_type: str,
    value: str,
    *,
    tier: DetectionTier = DetectionTier.RULE_ANCHORED,
    confidence: float = 1.0,
) -> DetectedPII:
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        start_idx=0,
        end_idx=len(value),
        confidence=confidence,
        tier=tier,
        source="test",
    )


def test_direct_identifier_is_tokenized_independent_of_score() -> None:
    result = calculate_weighted_risk([detection("PERSON_KO", "홍길동")])

    assert result.action == "TOKENIZE"
    assert result.identification > 0.8


def test_multiple_locations_remain_one_qi_category() -> None:
    result = calculate_weighted_risk(
        [
            detection("LOCATION_INFORMAL", "역삼동"),
            detection("LOCATION_INFORMAL", "강남구"),
        ]
    )

    assert result.qi_category_count == 1
    assert result.combination == 0.0


def test_unknown_entity_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported detected entity type") as exc_info:
        calculate_weighted_risk([detection("UNKNOWN_ENTITY", "미등록값")])
    assert "UNKNOWN_ENTITY" not in str(exc_info.value)
    assert "미등록값" not in str(exc_info.value)


@pytest.mark.parametrize("kind", ["PRODUCT_ITEM", "PURCHASE_PATTERN"])
def test_commerce_contributes_weight_without_becoming_sensitive(kind: str) -> None:
    result = calculate_weighted_risk([detection(kind, "테스트")])
    assert result.score > 0
    assert result.qi_category_count == 1
    assert result.action == "ALLOW"


def test_commerce_repetition_does_not_inflate_weighted_score() -> None:
    product = detection("PRODUCT_ITEM", "머그컵")
    pattern = detection("PURCHASE_PATTERN", "매주 구매")
    expected = calculate_weighted_risk([pattern])
    assert calculate_weighted_risk([product, pattern, product, pattern]) == expected
    assert calculate_weighted_risk([pattern, product]) == expected


def test_commerce_combines_with_age_and_location() -> None:
    result = calculate_weighted_risk(
        [
            detection("AGE", "30세"),
            detection("LOCATION", "강남구"),
            detection("PRODUCT_ITEM", "머그컵"),
            detection("PURCHASE_PATTERN", "매주 구매"),
        ]
    )
    assert result.qi_category_count == 3
    assert result.action == "GENERALIZE"


def test_sex_life_keeps_tokenization_priority() -> None:
    result = calculate_weighted_risk([detection("SENSITIVE_SEX_LIFE", "민감내용", confidence=0)])
    assert result.score == 0
    assert result.action == "TOKENIZE"


def test_weak_pattern_does_not_erase_stronger_product_evidence() -> None:
    product = detection("PRODUCT_ITEM", "머그컵")
    weak_pattern = detection("PURCHASE_PATTERN", "매주 구매", confidence=0)
    assert calculate_weighted_risk([product, weak_pattern]) == calculate_weighted_risk([product])


def test_missing_commerce_confidence_is_not_hidden_by_deduplication() -> None:
    product = detection("PRODUCT_ITEM", "머그컵").model_copy(update={"confidence": None})
    pattern = detection("PURCHASE_PATTERN", "매주 구매")
    with pytest.raises(ValueError, match="requires measured confidence"):
        calculate_weighted_risk([product, pattern])
