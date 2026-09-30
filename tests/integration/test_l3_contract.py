"""L5 contract coverage using manually constructed canonical fixtures."""

import pytest
from pydantic import ValidationError

from privacy_proxy.risk.score import assess_risk
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import DetectedPII, DetectionTier, EntityType, ProxyContext

L3_CASES = [
    ("PERSON_EN", "Alice", 80, "TOKENIZE"),
    ("LOCATION", "영통구", 15, "ALLOW"),
    ("ADDRESS", "서울시 테스트로 10", 80, "TOKENIZE"),
    ("AGE", "32", 20, "ALLOW"),
    ("AGE_GROUP", "30대", 8, "ALLOW"),
    ("DATE_OF_BIRTH", "1994-01-02", 22, "ALLOW"),
    ("KR_RRN", "900101-1234567", 80, "TOKENIZE"),
    ("PHONE_NUMBER", "010-1234-5678", 80, "TOKENIZE"),
    ("EMAIL_ADDRESS", "test@example.com", 80, "TOKENIZE"),
    ("KR_PASSPORT", "M12345678", 80, "TOKENIZE"),
    ("KR_FRN", "900101-5123456", 80, "TOKENIZE"),
    ("KR_DRIVER_LICENSE", "11-12-123456-78", 80, "TOKENIZE"),
    ("KR_BRN", "123-45-67890", 85, "TOKENIZE"),
]


def make_context(items: list[tuple[str, str]]) -> ProxyContext:
    text = " ".join(value for _, value in items)
    offset = 0
    detections = []
    for kind, value in items:
        detections.append(
            DetectedPII(
                entity_type=EntityType(kind),
                original_value=value,
                start_idx=offset,
                end_idx=offset + len(value),
                confidence=None,
                tier=DetectionTier.RULE_ANCHORED,
                source="L3_TEST",
            )
        )
        offset += len(value) + 1
    return ProxyContext(raw_prompt=text, detected_entities=detections)


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "value", "score", "action"), L3_CASES)
async def test_l3_names_pass_real_stage_with_nullable_confidence(
    kind: str,
    value: str,
    score: float,
    action: str,
) -> None:
    result = await run_l5_risk_scoring(make_context([(kind, value)]))
    assert result.status == "success"
    assert result.risk_score == score
    assert result.policy_action == action
    assert result.detected_entities[0].entity_type == kind


def test_demographic_signals_do_not_triple_count() -> None:
    result = assess_risk(
        make_context(
            [
                ("AGE", "32세"),
                ("AGE_GROUP", "30대"),
                ("DATE_OF_BIRTH", "1994-01-02"),
            ]
        )
    )
    assert result.risk_score == 22
    assert len(result.risk_reasons) == 1


def test_age_and_location_trigger_generalization() -> None:
    result = assess_risk(make_context([("AGE", "32세"), ("LOCATION", "영통구")]))
    assert result.risk_score == 43
    assert result.policy_action == "GENERALIZE"


def test_shared_location_names_are_deduplicated() -> None:
    result = assess_risk(
        make_context(
            [
                ("LOCATION", "영통구"),
                ("LOCATION_INFORMAL", "영통구"),
            ]
        )
    )
    assert result.risk_score == 15


def test_schema_validation_error_hides_input() -> None:
    with pytest.raises(ValidationError) as error:
        DetectedPII(
            entity_type="PHONE_NUMBER",
            original_value="private-value",
            start_idx=0,
            end_idx=13,
            confidence=2,
            tier="rule_anchored",
        )
    assert "input_value" not in str(error.value)
