"""Integration boundary tests for replacing mock_l5_risk_scoring."""

import pytest

from privacy_proxy.risk.resolver import resolve_overlaps
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


async def test_l5_passes_full_original_prompt_to_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "첫 번째 문장\n송장번호: 112412345601"
    value = "112412345601"
    entity = detection("TRACKING_NUMBER", value, prompt.index(value))
    received: list[str | None] = []

    def capture(entities: list[DetectedPII], *, raw_prompt: str | None = None) -> list[DetectedPII]:
        received.append(raw_prompt)
        assert raw_prompt is not None
        assert raw_prompt[entities[0].start_idx : entities[0].end_idx] == value
        return resolve_overlaps(entities, raw_prompt=raw_prompt)

    monkeypatch.setattr("privacy_proxy.risk.score.resolve_overlaps", capture)
    result = await run_l5_risk_scoring(ProxyContext(raw_prompt=prompt, detected_entities=[entity]))

    assert result.status == "success"
    assert received == [prompt]
    assert result.detected_entities == resolve_overlaps([entity])


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


@pytest.mark.parametrize("kind", ["SENSITIVE_RELIGION", "SENSITIVE_FAMILY", "SENSITIVE_FINANCIAL"])
async def test_removed_sensitive_types_stop_l5(kind: str) -> None:
    result = await run_l5_risk_scoring(
        ProxyContext(raw_prompt="테스트", detected_entities=[detection(kind, "테스트")])
    )
    assert result.status == "failed"
    assert result.error == "L5_VALIDATION_FAILED"
    assert result.policy_action is None


async def test_commerce_combination_runs_real_l5() -> None:
    result = await run_l5_risk_scoring(
        ProxyContext(
            raw_prompt="30세 머그컵",
            detected_entities=[detection("AGE", "30세"), detection("PRODUCT_ITEM", "머그컵", 4)],
        )
    )
    assert result.status == "success"
    assert result.risk_score == 33
    assert result.policy_action == "GENERALIZE"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("송장번호: 112412345601", "TRACKING_NUMBER"),
        ("송장번호는 별도입니다. 112412345601", "KR_DRIVER_LICENSE"),
    ],
)
async def test_l4_anchor_evidence_resolves_license_in_l5(text: str, expected: str) -> None:
    from l4.recognizers import find_tracking_number

    from privacy_proxy.l4_adapter import translate_segment_detection

    prefix = "앞선 메시지\n"
    [local] = find_tracking_number(text)
    number = translate_segment_detection(local, offset_base=len(prefix))
    license = DetectedPII(
        entity_type="KR_DRIVER_LICENSE",
        original_value=number.original_value,
        start_idx=number.start_idx,
        end_idx=number.end_idx,
        confidence=1.0,
        tier=DetectionTier.DETERMINISTIC,
        source="L3_Regex",
    )
    result = await run_l5_risk_scoring(
        ProxyContext(
            raw_prompt=prefix + text,
            detected_entities=[license, number],
        )
    )
    assert result.status == "success"
    assert [item.entity_type for item in result.detected_entities] == [expected]
    assert result.entity_policies[0].action == "TOKENIZE"


async def test_actual_l4_competing_labels_keep_direct_order_evidence() -> None:
    from itertools import permutations

    from l4.recognizers import find_order_id, find_tracking_number

    text = "송장번호는 별도입니다. 주문번호: 112412345601"
    [order] = find_order_id(text)
    [tracking] = find_tracking_number(text)
    license = DetectedPII(
        entity_type="KR_DRIVER_LICENSE",
        original_value=order.original_value,
        start_idx=order.start_idx,
        end_idx=order.end_idx,
        confidence=1.0,
        tier=DetectionTier.DETERMINISTIC,
        source="L3_Regex",
    )
    for sequence in permutations([order, tracking, license]):
        result = await run_l5_risk_scoring(
            ProxyContext(
                raw_prompt=text,
                detected_entities=list(sequence),
            )
        )
        assert result.status == "success"
        assert result.detected_entities == [order]
        assert result.detected_entities[0].anchor_text == "주문번호"
        assert result.entity_policies[0].action == "TOKENIZE"


@pytest.mark.parametrize(
    ("kind", "label", "value"),
    [
        ("ORDER_ID", "주문번호", "112412345601"),
        ("TRACKING_NUMBER", "송장번호", "112412345601"),
        ("CUSTOMER_ID", "고객번호", "112412345601"),
        ("ACCOUNT_NUMBER", "계좌번호", "123456-01-234567"),
    ],
)
async def test_merged_l4_number_anchors_reach_l5_with_global_offsets(kind, label, value):
    from itertools import permutations

    from l4.recognizers import (
        find_account_number,
        find_customer_id,
        find_order_id,
        find_tracking_number,
    )

    from privacy_proxy.l4_adapter import translate_segment_detection

    find = {
        "ORDER_ID": find_order_id,
        "TRACKING_NUMBER": find_tracking_number,
        "CUSTOMER_ID": find_customer_id,
        "ACCOUNT_NUMBER": find_account_number,
    }[kind]
    prefix = "이전 메시지입니다.\n"
    segment = f"{label}: {value}"
    [local] = find(segment, segment_id="seg-2")
    number = translate_segment_detection(local, offset_base=len(prefix))
    raw = prefix + segment
    assert number.anchor_text == label
    assert raw[number.anchor_start : number.anchor_end] == label
    assert raw[number.start_idx : number.end_idx] == value
    # Synthetic competing license isolates resolver behavior; this does not
    # claim that L3 emits a license for every account-number format.
    license = DetectedPII(
        entity_type="KR_DRIVER_LICENSE",
        original_value=value,
        start_idx=number.start_idx,
        end_idx=number.end_idx,
        segment_id="seg-2",
        confidence=1.0,
        tier=DetectionTier.DETERMINISTIC,
        source="L3_Regex",
    )
    for sequence in permutations([number, license]):
        result = await run_l5_risk_scoring(
            ProxyContext(raw_prompt=raw, detected_entities=list(sequence))
        )
        assert result.status == "success"
        assert result.detected_entities == [number]
        assert result.entity_policies[0].action == "TOKENIZE"
