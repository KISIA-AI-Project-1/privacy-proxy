"""R1: 세그먼트로 추출하지 않은 부가 필드가 외부 LLM 요청에 실리지 않는지 검증한다.

단위 테스트는 허용 목록 규칙을, 통합 테스트는 세 벤더 모두에 대해 **실제 HTTP transport에서
캡처한 전체 JSON**을 확인한다. 모든 값은 합성 데이터다.
"""

import json
import os
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from privacy_proxy.config import get_settings
from privacy_proxy.pipeline import run_privacy_pipeline
from privacy_proxy.request_fields import find_unsupported_fields
from privacy_proxy.schemas import UserContext

SYNTHETIC_EMAIL = "audit@example.com"
SYNTHETIC_PHONE = "010-9999-8888"
REAL_ASYNC_CLIENT = httpx.AsyncClient


def openai_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "안녕하세요"}],
        **extra,
    }


def claude_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "claude-3-5-sonnet",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "안녕하세요"}],
        **extra,
    }


def gemini_body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "gemini-1.5-pro",
        "contents": [{"role": "user", "parts": [{"text": "안녕하세요"}]}],
        **extra,
    }


BUILDERS = {"openai": openai_body, "anthropic": claude_body, "gemini": gemini_body}

# --------------------------------------------------------------------------- 단위: 허용 규칙


@pytest.mark.parametrize("vendor", sorted(BUILDERS))
def test_plain_request_is_allowed(vendor):
    assert find_unsupported_fields(vendor, BUILDERS[vendor]()) == []


@pytest.mark.parametrize(
    ("vendor", "extra"),
    [
        ("openai", {"temperature": 0.2, "max_tokens": 50, "top_p": 0.9, "stream": True}),
        ("openai", {"max_completion_tokens": 50, "seed": 7, "n": 1}),
        ("anthropic", {"temperature": 0.2, "top_p": 0.9, "top_k": 5, "stream": True}),
        (
            "gemini",
            {"generationConfig": {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": 64}},
        ),
    ],
)
def test_normal_model_options_are_allowed(vendor, extra):
    assert find_unsupported_fields(vendor, BUILDERS[vendor](**extra)) == []


@pytest.mark.parametrize(
    ("vendor", "extra", "path"),
    [
        ("openai", {"user": SYNTHETIC_EMAIL}, "user"),
        ("openai", {"metadata": {"phone": SYNTHETIC_PHONE}}, "metadata"),
        ("openai", {"stop": [SYNTHETIC_PHONE]}, "stop"),
        ("openai", {"temperature": SYNTHETIC_PHONE}, "temperature"),
        ("openai", {"max_tokens": True}, "max_tokens"),
        ("openai", {"logit_bias": {"1": 1}}, "logit_bias"),
        ("anthropic", {"metadata": {"user_id": SYNTHETIC_EMAIL}}, "metadata"),
        ("anthropic", {"stop_sequences": [SYNTHETIC_PHONE]}, "stop_sequences"),
        ("gemini", {"cachedContent": SYNTHETIC_EMAIL}, "cachedContent"),
        ("gemini", {"safetySettings": [{"category": SYNTHETIC_EMAIL}]}, "safetySettings"),
        (
            "gemini",
            {"generationConfig": {"stopSequences": [SYNTHETIC_PHONE]}},
            "generationConfig.stopSequences",
        ),
        (
            "gemini",
            {"generationConfig": {"temperature": SYNTHETIC_PHONE}},
            "generationConfig.temperature",
        ),
    ],
)
def test_unlisted_or_text_bearing_fields_are_reported(vendor, extra, path):
    assert path in find_unsupported_fields(vendor, BUILDERS[vendor](**extra))


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_message_extra_key_and_role_are_reported(vendor):
    body = BUILDERS[vendor]()
    body["messages"][0]["name"] = SYNTHETIC_EMAIL
    body["messages"][0]["role"] = SYNTHETIC_PHONE
    assert find_unsupported_fields(vendor, body) == ["messages[0].name", "messages[0].role"]


def test_gemini_content_extra_key_and_role_are_reported():
    body = gemini_body()
    body["contents"][0]["name"] = SYNTHETIC_EMAIL
    body["contents"][0]["role"] = SYNTHETIC_PHONE
    assert find_unsupported_fields("gemini", body) == ["contents[0].name", "contents[0].role"]


def test_reported_paths_never_contain_values():
    body = openai_body(user=SYNTHETIC_EMAIL, metadata={"phone": SYNTHETIC_PHONE})
    paths = " ".join(find_unsupported_fields("openai", body))
    assert SYNTHETIC_EMAIL not in paths
    assert SYNTHETIC_PHONE not in paths


def test_unknown_vendor_is_rejected():
    assert find_unsupported_fields("other", {"messages": []}) == ["<vendor>"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_non_finite_numbers_are_rejected(vendor, bad):
    assert "temperature" in find_unsupported_fields(vendor, BUILDERS[vendor](temperature=bad))


def test_non_finite_number_in_gemini_config_is_rejected():
    body = gemini_body(generationConfig={"temperature": float("nan")})
    assert find_unsupported_fields("gemini", body) == ["generationConfig.temperature"]


def test_huge_integer_does_not_crash_the_check():
    assert find_unsupported_fields("openai", openai_body(seed=10**400)) == []


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "content", [[{"type": "text", "text": SYNTHETIC_PHONE}], 12345, None, {"text": "x"}]
)
def test_non_string_content_is_reported(vendor, content):
    body = BUILDERS[vendor]()
    body["messages"][0]["content"] = content
    assert find_unsupported_fields(vendor, body) == ["messages[0].content"]


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_empty_messages_are_reported(vendor):
    body = BUILDERS[vendor]()
    body["messages"] = []
    assert find_unsupported_fields(vendor, body) == ["messages"]


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (
            [{"text": "안녕하세요", "unscanned_meta": SYNTHETIC_PHONE}],
            ["contents[0].parts[0].unscanned_meta"],
        ),
        (
            [{"text": "안녕하세요"}, {"inlineData": {"data": SYNTHETIC_EMAIL}}],
            ["contents[0].parts[1].inlineData", "contents[0].parts[1].text"],
        ),
        ([{"text": 123}], ["contents[0].parts[0].text"]),
        ([], ["contents[0].parts"]),
        ("텍스트", ["contents[0].parts"]),
        (["문자열 part"], ["contents[0].parts[0]"]),
    ],
)
def test_gemini_parts_internals_are_checked(parts, expected):
    """검수 지적: parts 안쪽을 보지 않던 빈틈. 파이프라인 기존 검사에 기대지 않고 여기서 막는다."""
    body = gemini_body()
    body["contents"][0]["parts"] = parts
    assert find_unsupported_fields("gemini", body) == expected


def test_gemini_without_contents_is_reported():
    assert find_unsupported_fields("gemini", {"model": "gemini-1.5-pro", "contents": []}) == [
        "contents"
    ]


# ----------------------------------------------------------------------- 통합: 실제 전송 본문


class EmptyDetector:
    def analyze(self, **kwargs):
        return []


async def run_and_capture(body: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    """파이프라인을 실제로 돌리고 httpx transport에 도달한 전체 JSON을 모은다."""
    captured: list[dict[str, Any]] = []

    def intercept(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            # 세 벤더 파서가 모두 "텍스트 없는 이벤트"로 넘기는 빈 스트림.
            content=b'data: {"type": "message_stop"}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    env = {
        "OPENAI_API_KEY": "synthetic-only",
        "CLAUDE_API_KEY": "synthetic-only",
        "GEMINI_API_KEY": "synthetic-only",
        "AUDIT_S3_ENABLED": "false",
        "VAULT_BACKEND": "memory",
        "L4_NER_ENABLED": "false",
    }
    with (
        patch.dict(os.environ, env),
        patch("privacy_proxy.pipeline._get_l3_service", return_value=EmptyDetector()),
        patch("privacy_proxy.pipeline.detect_l4_ner", return_value=[]),
        patch(
            "upstream.llm_client.httpx.AsyncClient",
            side_effect=lambda **kwargs: REAL_ASYNC_CLIENT(
                transport=httpx.MockTransport(intercept), **kwargs
            ),
        ),
    ):
        get_settings.cache_clear()
        try:
            context = await run_privacy_pipeline(
                body,
                UserContext(
                    user_id="test",
                    department="test",
                    role="developer",
                    allowed_models=["gpt-4o-mini", "claude-3-5-sonnet", "gemini-1.5-pro"],
                ),
            )
            if context.status == "success":
                async for _ in context.final_response:
                    pass
        finally:
            get_settings.cache_clear()
    return context, captured


@pytest.mark.parametrize("vendor", sorted(BUILDERS))
@pytest.mark.parametrize(
    "extra",
    [
        {"user": SYNTHETIC_EMAIL},
        {"metadata": {"phone": SYNTHETIC_PHONE}},
    ],
)
async def test_unscanned_extra_field_is_blocked_before_http(vendor, extra):
    if vendor == "gemini":
        extra = {"cachedContent": json.dumps(extra)}
    context, captured = await run_and_capture(BUILDERS[vendor](**extra))

    assert context.status == "failed"
    assert context.error == "L2_UNSUPPORTED_FIELD"
    assert captured == []


@pytest.mark.parametrize("vendor", sorted(BUILDERS))
async def test_text_bearing_message_key_is_blocked_before_http(vendor):
    body = BUILDERS[vendor]()
    target = body["contents"][0] if vendor == "gemini" else body["messages"][0]
    target["name"] = SYNTHETIC_EMAIL
    context, captured = await run_and_capture(body)

    assert context.error == "L2_UNSUPPORTED_FIELD"
    assert captured == []


@pytest.mark.parametrize("vendor", sorted(BUILDERS))
async def test_normal_request_reaches_http_with_options_and_without_synthetic_values(vendor):
    options = {
        "openai": {"temperature": 0.2, "max_tokens": 50},
        "anthropic": {"temperature": 0.2},
        "gemini": {"generationConfig": {"temperature": 0.2, "maxOutputTokens": 64}},
    }[vendor]
    context, captured = await run_and_capture(BUILDERS[vendor](**options))

    assert context.status == "success", context.error
    assert len(captured) == 1
    sent = captured[0]
    # 정상 옵션은 그대로 유지된다.
    if vendor == "gemini":
        assert sent["generationConfig"] == options["generationConfig"]
    else:
        assert sent["temperature"] == 0.2
    # 전체 JSON을 검사한다: 합성 값이 어디에도 없어야 한다.
    serialized = json.dumps(sent, ensure_ascii=False)
    assert SYNTHETIC_EMAIL not in serialized
    assert SYNTHETIC_PHONE not in serialized


async def test_prompt_value_is_still_tokenized_in_the_full_outgoing_json():
    """L4 인식기가 잡는 본문 값은 기존대로 치환되고, 허용된 옵션은 영향을 받지 않는다."""
    order_number = "2026101112345"
    body = openai_body(temperature=0.1)
    body["messages"][0]["content"] = f"주문번호 {order_number} 환불 문의"
    context, captured = await run_and_capture(body)

    assert context.status == "success", context.error
    assert len(captured) == 1
    assert order_number not in json.dumps(captured[0], ensure_ascii=False)
    assert captured[0]["temperature"] == 0.1
