"""Check that E2E cannot silently pass missing/misjoined applied results."""

from copy import deepcopy

import httpx
import pytest
from e2e_leak_test import Case, evaluate, validate_applied


def response_data():
    row = {"segment_id": "seg-1", "start_idx": 0, "end_idx": 2, "entity_type": "PURCHASE_PATTERN"}
    return {
        "risk": {"entity_policies": [{**row, "action": "ALLOW", "applied": "KEEP"}]},
        "anonymization": {"entity_outcomes": [{**row, "action": "KEEP"}]},
    }


def test_allow_keep_is_a_valid_join():
    assert validate_applied(response_data()) == []


@pytest.mark.parametrize(
    "change", ["missing", "wrong_action", "wrong_segment", "wrong_type", "duplicate"]
)
def test_broken_join_is_detected(change):
    data = response_data()
    rows = data["anonymization"]["entity_outcomes"]
    if change == "missing":
        rows.clear()
    elif change == "wrong_action":
        data["risk"]["entity_policies"][0]["applied"] = "TOKENIZE"
    elif change == "wrong_segment":
        rows[0]["segment_id"] = "seg-2"
    elif change == "wrong_type":
        rows[0]["entity_type"] = "PRODUCT_ITEM"
    else:
        rows.append(deepcopy(rows[0]))
    assert validate_applied(data)


def test_allowed_purchase_is_not_classified_as_a_leak():
    case = Case(
        "kept",
        "proxy",
        "매달 주문",
        kept=("매달",),
        required=("PURCHASE_PATTERN",),
        expected_actions=(("PURCHASE_PATTERN", "ALLOW", "KEEP"),),
    )
    data = response_data()
    data.update(
        detection={"entities": [{"entity_type": "PURCHASE_PATTERN"}]},
        response={"text": case.text, "before_restore": case.text},
        latency_ms={},
    )
    assert evaluate(case, httpx.Response(200, json=data), [case.text])["status"] == "PASS"
    data["risk"]["entity_policies"][0]["applied"] = None
    assert evaluate(case, httpx.Response(200, json=data), [case.text])["status"] == "FAIL"
