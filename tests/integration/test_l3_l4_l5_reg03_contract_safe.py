"""REG-03-B3-C: synthetic, contract-safe L3/L4/L5 regressions.

Number cases freeze the three approved behavior expectations from B3-A.
Address cases freeze raw offset safety and successful actual L5 execution,
NOT address winner/tier policy while PD-001 & PD-006 remain open.
No L4 NER, L6, L7, or whole-pipeline claim.
"""

import asyncio

import pytest
from l4.recognizers import (
    find_address_detail,
    find_address_lot,
    find_address_road,
    find_customs_clearance_id,
    find_tracking_number,
)

from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.pipeline import _to_detected_pii
from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import ProxyContext

SEGMENT = "reg03-b3c-synthetic"
NUMERIC_CASES = (
    (
        "CROSS-01",
        "송장번호: 112412345601",
        "TRACKING_NUMBER",
        (),
        ("TRACKING_NUMBER",),
        "TRACKING_NUMBER",
    ),
    (
        "CROSS-02",
        "운전면허번호: 112412345601",
        "TRACKING_NUMBER",
        ("KR_DRIVER_LICENSE",),
        (),
        "KR_DRIVER_LICENSE",
    ),
    (
        "CROSS-04",
        "개인통관고유부호 P123456789012",
        "CUSTOMS_CLEARANCE_ID",
        (),
        ("CUSTOMS_CLEARANCE_ID",),
        "CUSTOMS_CLEARANCE_ID",
    ),
)
ADDRESS_CASES = (
    (
        "CROSS-05-FULL",
        "서울특별시 강남구 가상테스트로 999 101동 1203호",
        1,
        {"ADDRESS_ROAD", "ADDRESS_DETAIL"},
    ),
    ("ROAD-ONLY", "테헤란로 123으로 배송", 0, {"ADDRESS_ROAD"}),
    ("DETAIL-ONLY", "배송 주소는 101동 1203호", 0, {"ADDRESS_DETAIL"}),
    ("LOT-ONLY", "서울특별시 강남구 역삼동 123-45", None, {"ADDRESS_LOT"}),
    (
        "ROAD-DETAIL",
        "배송 주소는 테헤란로 123 101동 1203호",
        None,
        {"ADDRESS_ROAD", "ADDRESS_DETAIL"},
    ),
)
L4_ADDRESS = (
    ("ADDRESS_ROAD", find_address_road),
    ("ADDRESS_LOT", find_address_lot),
    ("ADDRESS_DETAIL", find_address_detail),
)


@pytest.fixture(scope="module")
def l3_service():
    return L3AnalyzerService()


def _kind(item):
    return str(getattr(item.entity_type, "value", item.entity_type))


def _validate_offsets(raw, detections):
    for item in detections:
        assert item.segment_id == SEGMENT, "SEGMENT_MISMATCH"
        assert isinstance(item.start_idx, int) and isinstance(item.end_idx, int)
        assert 0 <= item.start_idx < item.end_idx <= len(raw), "SPAN_OUT_OF_BOUNDS"
        assert raw[item.start_idx : item.end_idx] == item.original_value, "RAW_OFFSET_MISMATCH"
        assert item.source and item.tier is not None, "PROVENANCE_MISSING"
        assert item.normalized is not None, "NORMALIZED_MISSING"
        anchor = getattr(item, "anchor_text", None)
        if anchor is not None:
            assert item.anchor_start is not None and item.anchor_end is not None
            assert raw[item.anchor_start : item.anchor_end] == anchor, "ANCHOR_OFFSET_MISMATCH"


def _run_l5(raw, l3, l4):
    combined = [*l3, *l4]
    _validate_offsets(raw, combined)
    ctx = ProxyContext(raw_prompt=raw, detected_entities=combined)
    ctx.validate_detected_spans()
    resolved = resolve_overlaps(combined, raw_prompt=raw)
    _validate_offsets(raw, resolved)
    final = asyncio.run(run_l5_risk_scoring(ctx))
    assert final.status == "success", "L5_STATUS_NOT_SUCCESS"
    assert final.policy_action is not None, "L5_ACTION_MISSING"
    _validate_offsets(raw, final.detected_entities)
    return resolved, final


@pytest.mark.parametrize(
    "case_id,raw,l4_type,expected_l3,expected_l4,winner",
    NUMERIC_CASES,
    ids=[c[0] for c in NUMERIC_CASES],
)
def test_approved_numeric_l3_l4_l5_contract(
    l3_service, case_id, raw, l4_type, expected_l3, expected_l4, winner
):
    l3 = l3_service.analyze(raw, SEGMENT, entities=["KR_DRIVER_LICENSE"])
    find_l4 = find_tracking_number if l4_type == "TRACKING_NUMBER" else find_customs_clearance_id
    l4 = [_to_detected_pii(item, 0) for item in find_l4(raw, segment_id=SEGMENT)]
    assert sorted(_kind(item) for item in l3) == sorted(expected_l3), case_id
    assert sorted(_kind(item) for item in l4) == sorted(expected_l4), case_id
    resolved, _ = _run_l5(raw, l3, l4)
    assert [_kind(item) for item in resolved] == [winner], case_id


@pytest.mark.parametrize(
    "case_id,raw,expected_l3,required_l4", ADDRESS_CASES, ids=[c[0] for c in ADDRESS_CASES]
)
def test_address_runtime_safety_without_policy_winner_freeze(
    l3_service, case_id, raw, expected_l3, required_l4
):
    l3 = l3_service.analyze(raw, SEGMENT, entities=["ADDRESS"])
    l4 = []
    for expected_type, finder in L4_ADDRESS:
        detected = [_to_detected_pii(item, 0) for item in finder(raw, segment_id=SEGMENT)]
        assert all(_kind(item) == expected_type for item in detected), case_id
        l4.extend(detected)
    if expected_l3 is not None:
        assert len(l3) == expected_l3, "B3B0_L3_PARITY_MISMATCH"
    assert required_l4 <= {_kind(item) for item in l4}, "REQUIRED_L4_PRODUCER_MISSING"
    _run_l5(raw, l3, l4)
    # Deliberately no winner, tier, exact L4 count or action-type assertion.
    # PD-001=REVIEW_REQUIRED and PD-006=OPEN.
