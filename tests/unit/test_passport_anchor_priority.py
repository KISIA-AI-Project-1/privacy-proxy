"""Narrow same-span passport exception; all inputs are synthetic."""

import asyncio
from itertools import permutations

import pytest

from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def candidates(text: str, label: str, kind: str = "CUSTOMER_ID") -> tuple[DetectedPII, DetectedPII]:
    value = "M12345678"
    start = text.index(value)
    number = DetectedPII(
        entity_type=kind,
        original_value=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=0.4,
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_RECOGNIZER",
        anchor_text=label,
        anchor_start=text.index(label),
        anchor_end=text.index(label) + len(label),
    )
    passport = DetectedPII(
        entity_type="KR_PASSPORT",
        original_value=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=0.8,
        tier=DetectionTier.RULE_ANCHORED,
        source="L3_Regex",
    )
    return number, passport


@pytest.mark.parametrize(
    "kind,label",
    [
        ("CUSTOMER_ID", "고객번호"),
        ("CUSTOMER_ID", "고객 번호"),
        ("CUSTOMER_ID", "회원번호"),
        ("CUSTOMER_ID", "회원 번호"),
        ("ORDER_ID", "주문번호"),
        ("ORDER_ID", "주문 번호"),
        ("ORDER_ID", "구매번호"),
        ("ORDER_ID", "구매 번호"),
        ("TRACKING_NUMBER", "운송장번호"),
        ("TRACKING_NUMBER", "송장번호"),
        ("TRACKING_NUMBER", "송장 번호"),
        ("TRACKING_NUMBER", "택배번호"),
        ("TRACKING_NUMBER", "배송번호"),
    ],
)
def test_explicit_number_label_overrides_passport(kind: str, label: str) -> None:
    text = f"앞 문장\n{label}: M12345678"
    number, passport = candidates(text, label, kind)
    for sequence in permutations([number, passport]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [number]


@pytest.mark.parametrize("gap", ["\n", "는 별도이며 ", ". ", "       ", " " * 25])
def test_indirect_or_distant_anchor_keeps_passport(gap: str) -> None:
    text = f"고객번호{gap}M12345678"
    number, passport = candidates(text, "고객번호")
    for sequence in permutations([number, passport]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [passport]


@pytest.mark.parametrize("label", ["등록번호", "배송", "우리", "입금", "여권번호"])
def test_nonapproved_label_does_not_override_passport(label: str) -> None:
    text = f"{label} M12345678"
    number, passport = candidates(text, label)
    assert resolve_overlaps([number, passport], raw_prompt=text) == [passport]


@pytest.mark.parametrize(
    "updates",
    [
        {"source": "unknown"},
        {"tier": DetectionTier.MODEL},
        {"tier": DetectionTier.CANDIDATE},
        {"anchor_text": None, "anchor_start": None, "anchor_end": None},
        {"anchor_text": "회원번호"},
        {"entity_type": "ORDER_ID"},  # A customer label cannot establish an order.
        {"entity_type": "ACCOUNT_NUMBER"},
    ],
)
def test_invalid_number_evidence_does_not_override(updates: dict) -> None:
    text = "고객번호 M12345678"
    number, passport = candidates(text, "고객번호")
    number = number.model_copy(update=updates)
    # Preserve the baseline ordering; ORDER_ID already sorts above KR_PASSPORT.
    expected = resolve_overlaps([number, passport])
    assert resolve_overlaps([number, passport], raw_prompt=text) == expected


def test_missing_prompt_keeps_passport() -> None:
    number, passport = candidates("고객번호 M12345678", "고객번호")
    assert resolve_overlaps([number, passport]) == [passport]


def test_deterministic_passport_is_preserved() -> None:
    text = "고객번호 M12345678"
    number, passport = candidates(text, "고객번호")
    passport = passport.model_copy(update={"tier": DetectionTier.DETERMINISTIC})
    assert resolve_overlaps([number, passport], raw_prompt=text) == [passport]


def test_exception_requires_same_segment_and_exact_span() -> None:
    text = "고객번호 M12345678"
    number, passport = candidates(text, "고객번호")
    other_segment = number.model_copy(update={"segment_id": "other"})
    assert len(resolve_overlaps([other_segment, passport], raw_prompt=text)) == 2
    shorter = number.model_copy(
        update={"end_idx": number.end_idx - 1, "original_value": number.original_value[:-1]}
    )
    assert resolve_overlaps([shorter, passport], raw_prompt=text) == [passport]


def test_conflicting_direct_number_types_do_not_enable_exception() -> None:
    text = "고객번호 M12345678은 주문번호"
    customer, passport = candidates(text, "고객번호")
    order, _ = candidates(text, "주문번호", "ORDER_ID")
    for sequence in permutations([customer, order, passport]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == resolve_overlaps(list(sequence))


def test_unrelated_deterministic_detection_keeps_priority() -> None:
    text = "고객번호 M12345678"
    number, passport = candidates(text, "고객번호")
    other = passport.model_copy(
        update={"entity_type": "KR_RRN", "tier": DetectionTier.DETERMINISTIC}
    )
    assert resolve_overlaps([number, passport, other], raw_prompt=text) == [other]


@pytest.mark.parametrize(
    "label,kind", [("고객번호", "CUSTOMER_ID"), ("운송장번호", "TRACKING_NUMBER")]
)
def test_l5_stage_uses_number_classification(label: str, kind: str) -> None:
    text = f"{label} M12345678"
    number, passport = candidates(text, label, kind)
    result = asyncio.run(
        run_l5_risk_scoring(ProxyContext(raw_prompt=text, detected_entities=[passport, number]))
    )
    assert result.status == "success"
    assert result.detected_entities == [number]
    assert result.policy_action == "TOKENIZE"
