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
