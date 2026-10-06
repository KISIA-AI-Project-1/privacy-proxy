"""Regression coverage for nullable producer scores and safe overlap handling."""

from itertools import permutations

import pytest
from pydantic import ValidationError

from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.risk.weighted_score import calculate_weighted_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def entity(
    kind: str = "PHONE_NUMBER",
    confidence: float | None = None,
    tier: DetectionTier = DetectionTier.RULE_ANCHORED,
    start: int = 0,
    end: int = 4,
    source: str = "producer",
) -> DetectedPII:
    return DetectedPII(
        entity_type=kind,
        original_value="abcdefgh"[start:end],
        start_idx=start,
        end_idx=end,
        confidence=confidence,
        tier=tier,
        source=source,
    )


@pytest.mark.parametrize(
    "field,value",
    [("confidence", -0.1), ("confidence", 1.1), ("confidence", float("nan")), ("tier", None)],
)
def test_invalid_contract_values(field: str, value: object) -> None:
    payload = entity().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        DetectedPII.model_validate(payload)


@pytest.mark.parametrize("field", ["confidence", "tier"])
def test_required_fields_cannot_be_omitted(field: str) -> None:
    payload = entity().model_dump()
    del payload[field]
    with pytest.raises(ValidationError):
        DetectedPII.model_validate(payload)


def test_validation_error_hides_private_input() -> None:
    private_value = "private-person@example.com"
    payload = entity().model_dump()
    payload["original_value"] = private_value
    payload["confidence"] = 2.0

    with pytest.raises(ValidationError) as exc_info:
        DetectedPII.model_validate(payload)

    assert private_value not in str(exc_info.value)


def test_null_roundtrip() -> None:
    payload = entity().model_dump(mode="json")
    assert payload["confidence"] is None
    assert payload["tier"] == "rule_anchored"
    assert DetectedPII.model_validate(payload).confidence is None


@pytest.mark.parametrize(
    "kind,score,action",
    [
        ("PHONE_NUMBER", 80, "TOKENIZE"),
        ("ORDER_ID", 85, "TOKENIZE"),
        ("LOCATION_INFORMAL", 5, "ALLOW"),
        ("SENSITIVE_HEALTH", 80, "TOKENIZE"),
        ("SENSITIVE_SEX_LIFE", 80, "TOKENIZE"),
        ("PRODUCT_ITEM", 5, "ALLOW"),
        ("PURCHASE_PATTERN", 12, "ALLOW"),
    ],
)
async def test_null_score_runs_real_stage(kind: str, score: float, action: str) -> None:
    result = await run_l5_risk_scoring(
        ProxyContext(raw_prompt="abcd", detected_entities=[entity(kind)])
    )
    assert result.status == "success"
    assert result.risk_score == score
    assert result.policy_action == action
    if kind in {"SENSITIVE_HEALTH", "SENSITIVE_SEX_LIFE"}:
        assert "미산정" in " ".join(result.risk_reasons)


async def test_sensitive_zero_is_not_missing() -> None:
    result = await run_l5_risk_scoring(
        ProxyContext(raw_prompt="abcd", detected_entities=[entity("SENSITIVE_HEALTH", 0.0)])
    )
    assert result.risk_score == 0
    assert result.policy_action == "TOKENIZE"


@pytest.mark.parametrize("confidence", [None, 0.7])
def test_tier_beats_model_confidence(confidence: float | None) -> None:
    high = entity("KR_RRN", confidence, DetectionTier.DETERMINISTIC)
    low = entity("PERSON_KO", 0.99, DetectionTier.MODEL)
    for sequence in permutations([high, low]):
        assert resolve_overlaps(list(sequence)) == [high]


def test_comparable_scores_and_null_group_are_order_independent() -> None:
    high, low = entity(confidence=0.9), entity(confidence=0.2)
    assert resolve_overlaps([low, high]) == [high]
    unknown = entity()
    results = [resolve_overlaps(list(items)) for items in permutations([high, low, unknown])]
    assert all(result == results[0] for result in results)


def test_different_sources_do_not_compete_on_confidence() -> None:
    a = entity(confidence=0.99, source="a")
    z = entity(confidence=0.01, source="z")
    assert resolve_overlaps([a, z]) == [z]
    assert resolve_overlaps([a.model_copy(update={"confidence": 0.0}), z]) == [z]


@pytest.mark.parametrize(
    "start,end,kind", [(2, 6, "PERSON_KO"), (0, 6, "PERSON_KO"), (0, 4, "SENSITIVE_HEALTH")]
)
async def test_unsafe_overlap_fails_without_discarding_input(
    start: int, end: int, kind: str
) -> None:
    # The final case checks a high-tier QI cannot suppress tokenization.
    winner = entity(
        "LOCATION_INFORMAL" if kind == "SENSITIVE_HEALTH" else "KR_RRN",
        None,
        DetectionTier.DETERMINISTIC,
    )
    loser = entity(kind, 0.99, DetectionTier.CANDIDATE, start, end)
    original = [winner, loser]
    result = await run_l5_risk_scoring(
        ProxyContext(raw_prompt="abcdefgh", detected_entities=original)
    )
    assert result.status == "failed"
    assert result.error == "L5_VALIDATION_FAILED"
    assert result.detected_entities == original
    assert result.policy_action is None


def test_weighted_draft_does_not_invent_missing_confidence() -> None:
    with pytest.raises(ValueError, match="measured confidence"):
        calculate_weighted_risk([entity()])
