"""Real FastAPI/L1-L9 regression runner; only external LLM HTTP is echoed.

Run: uv run --extra detection-l3 python e2e_leak_test.py
No separately running server or real API key is needed. spaCy models are required.
Exit 0: all checks passed; 1: regression failures; 2: dependencies not ready.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Allow direct invocation without an editable project install.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import httpx
from fastapi.testclient import TestClient

from privacy_proxy.config import get_settings

PHONE = "010-9999-8888"


@dataclass(frozen=True)
class Case:
    name: str
    scope: str
    text: str
    protected: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    restore: bool = True
    repeat_phone: bool = False
    no_detections: bool = False
    kept: tuple[str, ...] = ()
    expected_actions: tuple[tuple[str, str, str], ...] = ()
    expected_response: str | None = None


CASES = (
    Case("plain", "proxy", "오늘 날씨가 맑아요", no_detections=True),
    Case("phone", "proxy", f"연락처 {PHONE}", (PHONE,), ("PHONE_NUMBER",)),
    Case(
        "repeat_phone",
        "proxy",
        f"연락처 {PHONE}, 다시 {PHONE}",
        (PHONE,),
        ("PHONE_NUMBER",),
        repeat_phone=True,
    ),
    Case("email", "proxy", "이메일 audit@example.com", ("audit@example.com",), ("EMAIL_ADDRESS",)),
    Case(
        "account_1",
        "proxy",
        "환불 계좌번호 123456-01-234567입니다",
        ("123456-01-234567",),
        ("ACCOUNT_NUMBER",),
    ),
    Case(
        "account_2",
        "proxy",
        "신한은행 계좌 110-123-456789",
        ("110-123-456789",),
        ("ACCOUNT_NUMBER",),
    ),
    Case(
        "detail_tokenize",
        "proxy",
        f"연락처 {PHONE}. 배송 주소는 101동 1203호",
        (PHONE, "101동 1203호"),
        ("PHONE_NUMBER", "ADDRESS_DETAIL"),
    ),
    Case(
        "road_tokenize",
        "proxy",
        f"연락처 {PHONE}. 테헤란로 123으로 배송",
        (PHONE, "테헤란로 123"),
        ("PHONE_NUMBER", "ADDRESS_ROAD"),
    ),
    Case("health", "proxy", "저는 당뇨가 있어요", ("당뇨",), ("SENSITIVE_HEALTH",)),
    Case(
        "product_generalized_low_risk",
        "proxy",
        "매달 임신테스트기를 주문해요.",
        protected=("임신테스트기",),
        required=("PRODUCT_ITEM", "PURCHASE_PATTERN"),
        restore=False,
        kept=("매달",),
        expected_actions=(
            ("PRODUCT_ITEM", "GENERALIZE", "GENERALIZE"),
            ("PURCHASE_PATTERN", "ALLOW", "KEEP"),
        ),
        expected_response="매달 상품을 주문해요.",
    ),
    Case(
        "age_kept_with_phone",
        "proxy",
        f"저는 30대입니다. 연락처 {PHONE}",
        protected=(PHONE,),
        required=("AGE_GROUP", "PHONE_NUMBER"),
        kept=("30대",),
        expected_actions=(("AGE_GROUP", "ALLOW", "KEEP"), ("PHONE_NUMBER", "TOKENIZE", "TOKENIZE")),
    ),
    Case(
        "purchase_protected_with_generalized_qis",
        "proxy",
        f"저는 35세입니다. 신림동에 살아요. 매달 임신테스트기를 주문해요. 연락처 {PHONE}",
        protected=("35세", "신림동", "임신테스트기", PHONE),
        required=("AGE", "LOCATION", "PRODUCT_ITEM", "PURCHASE_PATTERN", "PHONE_NUMBER"),
        restore=False,
        kept=("매달",),
        expected_response=f"저는 30대입니다. 【LOCATION】에 살아요. 매달 상품을 주문해요. 연락처 {PHONE}",
        expected_actions=(
            ("AGE", "GENERALIZE", "GENERALIZE"),
            ("LOCATION", "GENERALIZE", "GENERALIZE"),
            ("PRODUCT_ITEM", "GENERALIZE", "GENERALIZE"),
            ("PURCHASE_PATTERN", "ALLOW", "KEEP"),
            ("PHONE_NUMBER", "TOKENIZE", "TOKENIZE"),
        ),
    ),
    Case("name_1", "team", "안녕하세요 김서연입니다", ("김서연",), ("PERSON_KO",)),
    Case("name_2", "team", "저는 최영수입니다", ("최영수",), ("PERSON_KO",)),
    Case("name_3", "team", "고객 이름은 김민지입니다", ("김민지",), ("PERSON_KO",)),
    Case(
        "customs", "team", "통관부호 P123456789012", ("P123456789012",), ("CUSTOMS_CLEARANCE_ID",)
    ),
    Case("order_type", "team", "주문번호 2026101112345", ("2026101112345",), ("ORDER_ID",)),
    Case("tracking_type", "team", "송장번호 112412345601", ("112412345601",), ("TRACKING_NUMBER",)),
    Case(
        "detail_address_protection",
        "team",
        "배송 주소는 101동 1203호",
        ("101동 1203호",),
        ("ADDRESS_DETAIL",),
        restore=False,
    ),
    Case("age_1", "team", "30대 초반이에요", required=("AGE_GROUP",)),
    Case("age_2", "team", "30대 여성이고", required=("AGE_GROUP",)),
)


def validate_applied(data: dict[str, Any]) -> list[str]:
    """Cross-check each L5 display row with the actual L6 result, by coordinates."""
    policies = data.get("risk", {}).get("entity_policies")
    outcomes = data.get("anonymization", {}).get("entity_outcomes")
    if not isinstance(policies, list) or not isinstance(outcomes, list):
        return ["MISSING_POLICY_OR_OUTCOME_LIST"]
    actual = {}
    failures: list[str] = []
    for outcome in outcomes:
        key = (outcome["segment_id"], outcome["start_idx"], outcome["end_idx"])
        if key in actual:
            failures.append("DUPLICATE_OUTCOME_COORDINATES")
        actual[key] = outcome
        if outcome["action"] not in {"TOKENIZE", "GENERALIZE", "KEEP", "SKIPPED"}:
            failures.append("INVALID_OUTCOME_ACTION")
        if outcome["action"] == "SKIPPED":
            failures.append("UNEXPECTED_SKIPPED_IN_STRICT_MODE")
    seen = set()
    for policy in policies:
        key = (policy["segment_id"], policy["start_idx"], policy["end_idx"])
        if key in seen:
            failures.append("DUPLICATE_POLICY_COORDINATES")
        seen.add(key)
        outcome = actual.get(key)
        if outcome is None:
            failures.append("MISSING_L6_OUTCOME")
        elif (
            policy.get("applied") != outcome["action"]
            or policy["entity_type"] != outcome["entity_type"]
        ):
            failures.append("APPLIED_OUTCOME_MISMATCH")
    if set(actual) != seen:
        failures.append("POLICY_OUTCOME_COVERAGE_MISMATCH")
    return failures


def evaluate(case: Case, response: httpx.Response, sent: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"case": case.name, "scope": case.scope, "http": response.status_code}
    data = response.json()
    if response.status_code != 200:
        result.update(
            status="BLOCKED" if not sent else "REQUEST_FAILED",
            error=data.get("detail", "HTTP_ERROR"),
        )
        return result
    if len(sent) != 1:
        result.update(status="FAIL", error="EXPECTED_ONE_UPSTREAM_REQUEST")
        return result
    outgoing = sent[0]
    kinds = {item["entity_type"] for item in data["detection"]["entities"]}
    leaks = [value for value in case.protected if value in outgoing]
    missing = [kind for kind in case.required if kind not in kinds]
    failures: list[str] = validate_applied(data)
    for value in case.kept:
        if value not in outgoing:
            failures.append("EXPECTED_KEPT_VALUE_MISSING")
    for kind, planned, applied in case.expected_actions:
        rows = [
            row for row in data["risk"].get("entity_policies", []) if row["entity_type"] == kind
        ]
        if not rows or any(
            row["action"] != planned or row.get("applied") != applied for row in rows
        ):
            failures.append(f"EXPECTED_ACTION_MISMATCH:{kind}")
    if case.expected_response is not None and data["response"]["text"] != case.expected_response:
        failures.append("GENERALIZED_RESPONSE_MISMATCH")
    if case.name == "health":
        tokens = data["anonymization"]["tokens"]
        if not any(
            item["entity_type"] == "SENSITIVE_HEALTH" and ":건강정보】" in item["token"]
            for item in tokens
        ):
            failures.append("HEALTH_HINT_MISSING")
    if case.restore and data["response"]["text"] != case.text:
        failures.append("RESTORATION_MISMATCH")
    if case.no_detections and kinds:
        failures.append("FALSE_POSITIVE")
    if data["response"]["before_restore"] != outgoing:
        failures.append("BEFORE_RESTORE_MISMATCH")
    if case.repeat_phone:
        tokens = [
            item["token"]
            for item in data["anonymization"]["tokens"]
            if item["entity_type"] == "PHONE_NUMBER"
        ]
        if len(tokens) != 1 or outgoing.count(tokens[0]) != 2:
            failures.append("REPEATED_PHONE_TOKEN_MISMATCH")
    result.update(
        status="LEAK" if leaks else "FAIL" if missing or failures else "PASS",
        leaked_values=leaks,
        missing_entities=missing,
        failures=failures,
        detected_types=sorted(kinds),
        latency_ms=data["latency_ms"],
    )
    return result


def run(scope: str) -> tuple[int, dict[str, Any]]:
    # Patch only test-process settings. Never modify .env or use real credentials.
    settings = {
        "DEMO_MODE": "true",
        "AUDIT_S3_ENABLED": "false",
        "VAULT_BACKEND": "memory",
        "PROXY_API_KEY": "synthetic-e2e-only",
        "OPENAI_API_KEY": "synthetic-upstream-only",
    }
    sent: list[str] = []

    def echo(request: httpx.Request) -> httpx.Response:
        if (
            request.method != "POST"
            or str(request.url) != "https://api.openai.com/v1/chat/completions"
        ):
            raise RuntimeError("UNEXPECTED_EXTERNAL_REQUEST")
        body = json.loads(request.content)
        text = body["messages"][-1]["content"]
        sent.append(text)
        events = [
            "data: "
            + json.dumps({"choices": [{"delta": {"content": text[start : start + 3]}}]})
            + "\n\n"
            for start in range(0, len(text), 3)
        ]
        return httpx.Response(
            200,
            content=("".join(events) + "data: [DONE]\n\n").encode(),
            headers={"content-type": "text/event-stream"},
        )

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(echo)
    report: dict[str, Any] = {"scope": scope, "chunk_size": 3, "results": []}
    with (
        patch.dict(os.environ, settings),
        patch(
            "upstream.llm_client.httpx.AsyncClient",
            side_effect=lambda **kwargs: client_type(transport=transport, **kwargs),
        ),
    ):
        get_settings.cache_clear()
        try:
            from privacy_proxy.main import app
        except ImportError:
            get_settings.cache_clear()
            report.update(
                status="NOT_READY",
                readiness_http=None,
                security={"unauthenticated_http": None, "upload_log_http": None},
                error="APPLICATION_DEPENDENCY_IMPORT_FAILED",
            )
            return 2, report
        try:
            with TestClient(app) as client:
                auth = client.post("/v1/demo/chat", json={}).status_code
                removed = client.post(
                    "/v1/upload-log", params={"filename": "synthetic", "content": "synthetic"}
                ).status_code
                report["security"] = {"unauthenticated_http": auth, "upload_log_http": removed}
                ready = client.get("/readyz")
                report["readiness_http"] = ready.status_code
                if ready.status_code != 200:
                    report["status"] = "NOT_READY"
                    return 2, report
                for case in CASES:
                    if scope != "all" and case.scope != scope:
                        continue
                    sent.clear()
                    response = client.post(
                        "/v1/demo/chat",
                        headers={"Authorization": "Bearer synthetic-e2e-only"},
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [{"role": "user", "content": case.text}],
                        },
                    )
                    report["results"].append(evaluate(case, response, sent))
        finally:
            get_settings.cache_clear()
    failed = sum(item["status"] != "PASS" for item in report["results"])
    report.update(passed=len(report["results"]) - failed, failed=failed)
    security_ok = auth == 401 and removed == 404
    report["status"] = "PASS" if not failed and security_ok else "FAIL"
    return (0 if report["status"] == "PASS" else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("all", "proxy", "team"), default="all")
    parser.add_argument(
        "--report", type=Path, help="Optional JSON report containing synthetic test values only"
    )
    args = parser.parse_args()
    code, report = run(args.scope)
    print(f"Security: {report['security']}; readiness HTTP {report['readiness_http']}")
    if code == 2:
        if report.get("error"):
            print(f"Reason: {report['error']}")
        print(
            "NOT READY: no E2E case passed. Check spaCy models, DLL policy and server dependencies."
        )
    else:
        for item in report["results"]:
            print(f"[{item['scope']}] {item['case']}: {item['status']} (HTTP {item['http']})")
            if item["status"] != "PASS":
                print(json.dumps(item, ensure_ascii=False))
        print(
            f"{report['passed']} passed / {report['failed']} failed. Team failures remain real failures."
        )
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.report}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
