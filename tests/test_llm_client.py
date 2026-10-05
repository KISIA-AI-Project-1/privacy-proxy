import copy
import json
from collections.abc import AsyncIterable, Callable
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest

from privacy_proxy.schemas import ParsedRequest, ProxyContext
from upstream.llm_client import PRIVACY_SYSTEM_SKILL, call_gemini_l7

VENDORS = ["openai", "anthropic", "gemini"]
PLACEHOLDER = "【PHONE_1】"
ORIGINAL_PHONE = "010-9999-8888"

# patch 적용 전 실제 클라이언트 클래스를 보관한다.
REAL_ASYNC_CLIENT = httpx.AsyncClient


def make_context(vendor: str) -> ProxyContext:
    """벤더별 가명화 완료 요청을 만든다."""
    body: dict[str, Any]

    if vendor == "openai":
        model = "gpt-4o-mini"
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"연락처: {PLACEHOLDER}",
                }
            ],
        }
    elif vendor == "anthropic":
        model = "test-claude-model"
        body = {
            "model": model,
            "max_tokens": 100,
            "messages": [
                {
                    "role": "user",
                    "content": f"연락처: {PLACEHOLDER}",
                }
            ],
        }
    else:
        model = "test-gemini-model"
        body = {
            "model": model,
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"연락처: {PLACEHOLDER}"}],
                }
            ],
        }

    return ProxyContext(
        raw_prompt=f"연락처: {ORIGINAL_PHONE}",
        parsed_request=ParsedRequest(
            vendor=vendor,
            model=model,
            segments=[],
            original_body=copy.deepcopy(body),
        ),
        reconstructed_body=body,
        anonymized_prompt=f"연락처: {PLACEHOLDER}",
        vault_mapping={PLACEHOLDER: ORIGINAL_PHONE},
        token_types={PLACEHOLDER: "PHONE_NUMBER"},
    )


def set_test_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트 프로세스 안에서만 사용할 가짜 환경변수를 설정한다."""
    for name in (
        "OPENAI_API_KEY",
        "CLAUDE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.setenv(name, "unit-test-placeholder")


def client_factory(
    transport: httpx.MockTransport,
) -> Callable[..., httpx.AsyncClient]:
    """모든 HTTP 요청을 실제 서버 대신 MockTransport로 보낸다."""

    def make_client(timeout: float = 30.0) -> httpx.AsyncClient:
        return REAL_ASYNC_CLIENT(
            transport=transport,
            timeout=timeout,
        )

    return make_client


def make_sse_response(vendor: str) -> str:
    """각 벤더 형식으로 동일한 텍스트 응답을 만든다."""
    events: list[dict[str, Any]]

    if vendor == "openai":
        events = [
            {"choices": [{"delta": {"content": "응답: "}}]},
            {"choices": [{"delta": {"content": PLACEHOLDER}}]},
        ]
    elif vendor == "anthropic":
        events = [
            {
                "type": "content_block_delta",
                "delta": {
                    "type": "text_delta",
                    "text": "응답: ",
                },
            },
            {
                "type": "content_block_delta",
                "delta": {
                    "type": "text_delta",
                    "text": PLACEHOLDER,
                },
            },
            {"type": "message_stop"},
        ]
    else:
        events = [
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "응답: "},
                                {"text": PLACEHOLDER},
                            ]
                        }
                    }
                ]
            }
        ]

    output = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)

    if vendor == "openai":
        output += "data: [DONE]\n\n"

    return output


async def read_response(context: ProxyContext) -> str:
    """L7 스트림을 실제로 소비한다."""
    assert context.llm_raw_response is not None
    stream = cast(AsyncIterable[str], context.llm_raw_response)
    chunks = [chunk async for chunk in stream]
    return "".join(chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", VENDORS)
async def test_l7_request_and_response(
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """가명화된 요청 전송과 벤더별 SSE 텍스트 해석을 검증한다."""
    set_test_keys(monkeypatch)
    context = make_context(vendor)
    original_body = copy.deepcopy(context.reconstructed_body)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text=make_sse_response(vendor),
        )

    transport = httpx.MockTransport(handler)

    with patch(
        "upstream.llm_client.httpx.AsyncClient",
        new=client_factory(transport),
    ):
        context = await call_gemini_l7(context)
        text = await read_response(context)

    assert context.status == "success"
    assert context.error is None
    assert text == f"응답: {PLACEHOLDER}"
    assert len(requests) == 1

    request = requests[0]
    assert request.method == "POST"

    sent_body = json.loads(request.content)
    serialized = json.dumps(sent_body, ensure_ascii=False)

    # 원문 개인정보와 복원 매핑이 전송되지 않는지 확인한다.
    assert ORIGINAL_PHONE not in serialized
    assert "vault_mapping" not in sent_body
    assert PLACEHOLDER in serialized
    assert PRIVACY_SYSTEM_SKILL in serialized.replace("\\n", "\n")

    # L7 내부 수정이 컨텍스트의 요청 원본을 변경하면 안 된다.
    assert context.reconstructed_body == original_body

    if vendor == "openai":
        assert request.url.host == "api.openai.com"
        assert sent_body["stream"] is True
        assert request.headers["Authorization"].startswith("Bearer ")
        assert sent_body["messages"][0]["role"] == "system"

    elif vendor == "anthropic":
        assert request.url.host == "api.anthropic.com"
        assert sent_body["stream"] is True
        assert "x-api-key" in request.headers
        assert sent_body["system"] == PRIVACY_SYSTEM_SKILL

    else:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert "test-gemini-model:streamGenerateContent" in request.url.path
        assert request.url.params["alt"] == "sse"
        assert "model" not in sent_body
        assert "x-goog-api-key" in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("status_code", [401, 503])
async def test_l7_http_error(
    vendor: str,
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """인증 오류와 서버 오류가 스트림 실패로 기록되는지 검증한다."""
    set_test_keys(monkeypatch)
    context = make_context(vendor)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": "test upstream failure"},
        )

    transport = httpx.MockTransport(handler)

    with patch(
        "upstream.llm_client.httpx.AsyncClient",
        new=client_factory(transport),
    ):
        context = await call_gemini_l7(context)

        with pytest.raises(httpx.HTTPStatusError):
            await read_response(context)

    assert context.status == "failed"
    assert context.error == "L7_STREAM_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", VENDORS)
async def test_l7_missing_api_key(
    vendor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API 키가 없으면 HTTP 요청 전에 실패 처리한다."""
    for name in (
        "OPENAI_API_KEY",
        "CLAUDE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    context = make_context(vendor)

    # 키 누락 시 클라이언트 생성 자체가 없어야 한다.
    with patch(
        "upstream.llm_client.httpx.AsyncClient",
    ) as mock_client:
        context = await call_gemini_l7(context)

    mock_client.assert_not_called()
    assert context.status == "failed"
    assert context.error == "L7_API_KEY_MISSING"
    assert context.llm_raw_response is None
