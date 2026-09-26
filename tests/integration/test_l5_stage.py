"""Integration boundary tests for replacing mock_l5_risk_scoring."""

import pytest

from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def detection(entity_type: str, value: str, start: int = 0) -> DetectedPII:
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=0.95,
        tier=DetectionTier.RULE_ANCHORED,
        source="integration-fixture",
    )


@pytest.mark.asyncio
async def test_confirmed_entity_runs_real_l5_assessment() -> None:
    value = "ORD-2026-001"
    context = ProxyContext(
        raw_prompt=value,
        detected_entities=[detection("ORDER_ID", value)],
    )

    result = await run_l5_risk_scoring(context)

    assert result.status == "success"
    assert result.risk_score == 85.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "TOKENIZE"
    assert "L5" in result.latency_ms


@pytest.mark.asyncio
async def test_noncanonical_entity_fails_closed_without_exposing_value() -> None:
    sample_value = "미등록값"
    context = ProxyContext(
        raw_prompt=sample_value,
        detected_entities=[detection("UNKNOWN_ENTITY", sample_value)],
    )

    result = await run_l5_risk_scoring(context)

    assert result.status == "failed"
    assert result.error == "L5_VALIDATION_FAILED"
    assert sample_value not in result.error
    assert result.policy_action is None


@pytest.mark.asyncio
async def test_span_mismatch_fails_closed_without_exposing_prompt() -> None:
    prompt = "홍길동의 주문"
    context = ProxyContext(
        raw_prompt=prompt,
        detected_entities=[detection("PERSON_KO", "김철수")],
    )

    result = await run_l5_risk_scoring(context)

    assert result.status == "failed"
    assert result.error == "L5_VALIDATION_FAILED"
    assert prompt not in result.error


@pytest.mark.asyncio
async def test_prefailed_context_is_not_evaluated() -> None:
    context = ProxyContext(status="failed", error="L4_FAILED")

    result = await run_l5_risk_scoring(context)

    assert result is context
    assert result.error == "L4_FAILED"
    assert "L5" not in result.latency_ms
