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


# ---------------------------------------------------------------------------
# R3: 계획(policy.action)과 L6 실제 처리(outcome.action)의 관계를 독립적으로 검증한다.
# `applied`는 outcome에서 만들어진 값이라 그것끼리의 비교는 증거가 되지 못한다.
# ---------------------------------------------------------------------------
from e2e_leak_test import (  # noqa: E402
    ALWAYS_TOKENIZED,
    CONTRACT_EXCEPTIONS,
    allowed_outcomes,
    validate_transformed,
)


def plan_and_outcome(entity_type, planned, actual, *, start=0, end=13):
    """`applied`는 실제 API처럼 outcome에서 그대로 만든다."""
    row = {"segment_id": "seg-1", "start_idx": start, "end_idx": end, "entity_type": entity_type}
    return {
        "risk": {"entity_policies": [{**row, "action": planned, "applied": actual}]},
        "anonymization": {"entity_outcomes": [{**row, "action": actual}]},
    }


def test_tokenize_planned_but_kept_is_rejected():
    """R3 재현 입력: 이전에는 오류 목록이 []였다."""
    errors = validate_applied(plan_and_outcome("PHONE_NUMBER", "TOKENIZE", "KEEP"))
    assert errors == ["POLICY_OUTCOME_VIOLATION:PHONE_NUMBER:TOKENIZE->KEEP"]


@pytest.mark.parametrize(
    ("entity_type", "planned", "actual"),
    [
        ("PHONE_NUMBER", "TOKENIZE", "TOKENIZE"),
        ("PERSON_KO", "TOKENIZE", "TOKENIZE"),
        ("LOCATION", "GENERALIZE", "GENERALIZE"),
        ("AGE", "GENERALIZE", "GENERALIZE"),
        ("AGE", "ALLOW", "KEEP"),
        ("PRODUCT_ITEM", "ALLOW", "KEEP"),
        ("PURCHASE_PATTERN", "ALLOW", "KEEP"),
        # 합의된 예외
        ("PRODUCT_ITEM", "GENERALIZE", "TOKENIZE"),
        ("LOCATION_INFORMAL", "GENERALIZE", "TOKENIZE"),
        ("AGE_GROUP", "GENERALIZE", "KEEP"),
        # L5는 생년월일을 준식별자로 보지만 L6는 항상 토큰화한다(보호 방향의 차이).
        ("DATE_OF_BIRTH", "TOKENIZE", "TOKENIZE"),
        ("DATE_OF_BIRTH", "ALLOW", "TOKENIZE"),
        ("DATE_OF_BIRTH", "GENERALIZE", "TOKENIZE"),
        # 주소류는 L5가 직접식별자로 분류하므로 계획은 항상 TOKENIZE다.
        ("ADDRESS_DETAIL", "TOKENIZE", "TOKENIZE"),
        ("ADDRESS", "TOKENIZE", "TOKENIZE"),
    ],
)
def test_allowed_plan_outcome_pairs_pass(entity_type, planned, actual):
    assert validate_applied(plan_and_outcome(entity_type, planned, actual)) == []


@pytest.mark.parametrize(
    ("entity_type", "planned", "actual"),
    [
        ("PHONE_NUMBER", "TOKENIZE", "KEEP"),
        ("PHONE_NUMBER", "TOKENIZE", "GENERALIZE"),
        ("LOCATION", "GENERALIZE", "KEEP"),
        ("LOCATION", "GENERALIZE", "TOKENIZE"),
        ("AGE", "ALLOW", "TOKENIZE"),
        ("PRODUCT_ITEM", "GENERALIZE", "KEEP"),
        ("PRODUCT_ITEM", "TOKENIZE", "KEEP"),
        ("LOCATION_INFORMAL", "GENERALIZE", "KEEP"),
        ("ADDRESS_DETAIL", "ALLOW", "KEEP"),
        ("ADDRESS_DETAIL", "ALLOW", "GENERALIZE"),
        ("ADDRESS_DETAIL", "TOKENIZE", "KEEP"),
        ("DATE_OF_BIRTH", "ALLOW", "KEEP"),
        ("DATE_OF_BIRTH", "GENERALIZE", "GENERALIZE"),
        # 계획이 TOKENIZE인데 유지하면 합의된 예외가 아니다.
        ("PURCHASE_PATTERN", "TOKENIZE", "KEEP"),
        ("PHONE_NUMBER", "TOKENIZE", "SKIPPED"),
    ],
)
def test_disallowed_plan_outcome_pairs_fail(entity_type, planned, actual):
    errors = validate_applied(plan_and_outcome(entity_type, planned, actual))
    # 다른 종류의 오류(좌표 불일치 등)가 아니라 정책 위반 때문에 실패해야 한다.
    assert any(
        e.startswith(("POLICY_OUTCOME_VIOLATION:", "POLICY_ACTION_NOT_ALLOWED:")) for e in errors
    ), errors


@pytest.mark.parametrize("planned", ["ALLOW", "GENERALIZE"])
def test_direct_identifier_must_be_planned_as_tokenize(planned):
    errors = validate_applied(plan_and_outcome("EMAIL_ADDRESS", planned, "TOKENIZE"))
    assert errors == ["POLICY_ACTION_NOT_ALLOWED:EMAIL_ADDRESS"]


def test_unknown_planned_action_fails():
    assert validate_applied(plan_and_outcome("AGE", "MASK", "TOKENIZE"))


def test_exception_table_is_explicit_and_small():
    """예외를 몰래 늘리면 이 테스트가 깨진다. 늘릴 때는 합의 후 여기도 고친다."""
    assert set(CONTRACT_EXCEPTIONS) == {
        ("PRODUCT_ITEM", "GENERALIZE"),
        ("LOCATION_INFORMAL", "GENERALIZE"),
        ("AGE_GROUP", "GENERALIZE"),
        ("DATE_OF_BIRTH", "ALLOW"),
        ("DATE_OF_BIRTH", "GENERALIZE"),
    }
    assert all(allowed_outcomes(kind, "TOKENIZE") for kind in ALWAYS_TOKENIZED)
    assert all(allowed_outcomes(kind, "GENERALIZE") is None for kind in ALWAYS_TOKENIZED)


def test_shifted_coordinates_are_detected():
    data = plan_and_outcome("PHONE_NUMBER", "TOKENIZE", "TOKENIZE")
    data["anonymization"]["entity_outcomes"][0]["start_idx"] = 1
    assert validate_applied(data)


# --- 실제 변환 문자열 검증 ---------------------------------------------------


def outcomes_data(text, *rows):
    return {
        "anonymization": {
            "entity_outcomes": [
                {
                    "segment_id": "seg-1",
                    "start_idx": text.index(raw),
                    "end_idx": text.index(raw) + len(raw),
                    "entity_type": kind,
                    "action": action,
                }
                for raw, kind, action in rows
            ]
        }
    }


def test_tokenized_value_still_in_outgoing_is_detected():
    text = "연락처 010-9999-8888"
    data = outcomes_data(text, ("010-9999-8888", "PHONE_NUMBER", "TOKENIZE"))
    assert validate_transformed(text, data, "연락처 【PHONE_1】") == []
    assert validate_transformed(text, data, text) == ["TOKENIZED_VALUE_IN_OUTGOING:PHONE_NUMBER"]


def test_kept_value_missing_from_outgoing_is_detected():
    text = "매달 주문"
    data = outcomes_data(text, ("매달", "PURCHASE_PATTERN", "KEEP"))
    assert validate_transformed(text, data, "매달 주문") == []
    assert validate_transformed(text, data, "【X】 주문") == [
        "KEPT_VALUE_MISSING_FROM_OUTGOING:PURCHASE_PATTERN"
    ]


def test_reported_tokenize_with_unchanged_outgoing_fails_evaluate():
    """보고값(TOKENIZE)은 맞는데 실제 문자열이 그대로면 evaluate가 FAIL을 낸다."""
    case = Case("phone", "proxy", "연락처 010-9999-8888", required=("PHONE_NUMBER",))
    data = plan_and_outcome("PHONE_NUMBER", "TOKENIZE", "TOKENIZE", start=4, end=17)
    data.update(
        detection={"entities": [{"entity_type": "PHONE_NUMBER"}]},
        response={"text": case.text, "before_restore": case.text},
        latency_ms={},
    )
    result = evaluate(case, httpx.Response(200, json=data), [case.text])
    assert result["status"] == "FAIL"
    assert "TOKENIZED_VALUE_IN_OUTGOING:PHONE_NUMBER" in result["failures"]


# --- R4 일부: 전체 JSON 캡처 -------------------------------------------------


def test_leak_outside_last_message_is_detected_with_full_body_capture():
    phone = "010-9999-8888"
    case = Case("plain", "proxy", "안녕하세요", protected=(phone,), no_detections=True)
    data = {
        "risk": {"entity_policies": []},
        "anonymization": {"entity_outcomes": []},
        "detection": {"entities": []},
        "response": {"text": case.text, "before_restore": case.text},
        "latency_ms": {},
    }
    response = httpx.Response(200, json=data)
    full_body = '{"messages": [{"role": "user", "content": "안녕하세요"}], "user": "' + phone + '"}'
    # 마지막 메시지만 보면 누출을 못 본다(기존 방식).
    assert evaluate(case, response, [case.text])["status"] == "PASS"
    # 전체 JSON을 보면 잡는다.
    assert evaluate(case, response, [case.text], [full_body])["status"] == "LEAK"


def test_token_hint_label_is_not_mistaken_for_a_leak():
    """【HEALTH_1:건강정보】의 라벨 글자가 원문과 같아도 오탐이 아니다."""
    text = "건강정보"
    data = outcomes_data(text, ("건강정보", "SENSITIVE_HEALTH", "TOKENIZE"))
    assert validate_transformed(text, data, "【HEALTH_1:건강정보】") == []
    # 토큰 밖에 원문이 남아 있으면 여전히 잡는다.
    assert validate_transformed(text, data, "【HEALTH_1:건강정보】 건강정보") == [
        "TOKENIZED_VALUE_IN_OUTGOING:SENSITIVE_HEALTH"
    ]
