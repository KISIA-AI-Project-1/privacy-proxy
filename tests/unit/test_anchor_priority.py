from itertools import permutations

import pytest

from privacy_proxy.risk.resolver import has_direct_anchor, resolve_overlaps
from privacy_proxy.schemas import DetectedPII, DetectionTier


def pair(text: str, kind: str = "TRACKING_NUMBER") -> tuple[DetectedPII, DetectedPII]:
    value = "112412345601"
    start = text.index(value)
    anchor = {
        "TRACKING_NUMBER": "송장번호",
        "ORDER_ID": "주문번호",
        "CUSTOMER_ID": "고객번호",
        "ACCOUNT_NUMBER": "계좌번호",
    }[kind]
    number = DetectedPII(
        entity_type=kind,
        original_value=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=0.4,
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_REGEX_TRACKING",
        anchor_text=anchor,
        anchor_start=text.index(anchor),
        anchor_end=text.index(anchor) + len(anchor),
    )
    license = DetectedPII(
        entity_type="KR_DRIVER_LICENSE",
        original_value=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=1.0,
        tier=DetectionTier.DETERMINISTIC,
        source="L3_Regex",
    )
    return number, license


@pytest.mark.parametrize("gap", ["", " ", ": ", "\uff1a", "는 ", "은: ", " = "])
def test_direct_label_overrides_license_in_either_input_order(gap: str) -> None:
    text = f"앞 문장\n송장번호{gap}112412345601"
    number, license = pair(text)
    for entities in permutations([number, license]):
        assert resolve_overlaps(list(entities), raw_prompt=text) == [number]
    assert number.tier == DetectionTier.RULE_ANCHORED


@pytest.mark.parametrize("gap", ["는 별도이며 ", ". ", "\n", ", ", "123 ", "       "])
def test_indirect_label_keeps_license(gap: str) -> None:
    text = f"송장번호{gap}112412345601"
    number, license = pair(text)
    assert resolve_overlaps([number, license], raw_prompt=text) == [license]


def test_right_label_and_missing_or_incorrect_evidence() -> None:
    text = "112412345601은 송장번호"
    number, license = pair(text)
    assert has_direct_anchor(number, text)
    assert resolve_overlaps([number, license], raw_prompt=text) == [number]
    assert resolve_overlaps([number, license]) == [license]
    assert not has_direct_anchor(number, text.replace("송장번호", "면허번호"))
    missing = number.model_copy(
        update={"anchor_text": None, "anchor_start": None, "anchor_end": None}
    )
    assert resolve_overlaps([missing, license], raw_prompt=text) == [license]


def test_unrelated_deterministic_detection_still_wins() -> None:
    text = "송장번호: 112412345601"
    number, license = pair(text)
    other = license.model_copy(update={"entity_type": "KR_RRN"})
    assert resolve_overlaps([number, license, other], raw_prompt=text) == [other]


def test_other_segment_or_non_l4_source_does_not_trigger_exception() -> None:
    text = "송장번호: 112412345601"
    number, license = pair(text)
    other = number.model_copy(update={"segment_id": "seg-2"})
    assert len(resolve_overlaps([other, license], raw_prompt=text)) == 2
    other = number.model_copy(update={"source": "unknown"})
    assert resolve_overlaps([other, license], raw_prompt=text) == [license]


def test_partial_overlap_retains_coverage_guard() -> None:
    text = "송장번호: 112412345601"
    number, license = pair(text)
    number = number.model_copy(
        update={"end_idx": number.end_idx - 1, "original_value": number.original_value[:-1]}
    )
    assert resolve_overlaps([number, license], raw_prompt=text) == [license]


@pytest.mark.parametrize("kind", ["ORDER_ID", "CUSTOMER_ID", "ACCOUNT_NUMBER"])
def test_other_number_types_use_the_same_exception(kind: str) -> None:
    label = {"ORDER_ID": "주문번호", "CUSTOMER_ID": "고객번호", "ACCOUNT_NUMBER": "계좌번호"}[kind]
    text = f"{label}: 112412345601"
    number, license = pair(text, kind)
    assert resolve_overlaps([number, license], raw_prompt=text) == [number]


@pytest.mark.parametrize("tier", [DetectionTier.MODEL, DetectionTier.CANDIDATE])
def test_weaker_tiers_do_not_override_license(tier: DetectionTier) -> None:
    text = "송장번호: 112412345601"
    number, license = pair(text)
    number = number.model_copy(update={"tier": tier})
    assert resolve_overlaps([number, license], raw_prompt=text) == [license]
