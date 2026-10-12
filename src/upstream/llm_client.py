import copy
import json
import os
from collections.abc import AsyncGenerator, AsyncIterable
from time import perf_counter
from typing import Any

import httpx

from privacy_proxy.config import get_settings
from privacy_proxy.schemas import ProxyContext

PRIVACY_SYSTEM_SKILL = """
당신은 개인정보 가명화 프록시를 거쳐 사용자와 소통하는 AI입니다.

입력에 포함된 가명과 토큰(예: 【PHONE_1】, 【EMAIL_1】, 홍길동)은
프록시에서 원래 개인정보 대신 넣은 값입니다.

- 답변에서 해당 정보를 인용할 때 가명과 토큰을 정확히 유지하세요.
- 토큰의 괄호, 이름, 숫자를 변경하거나 번역하지 마세요.
- 원래 개인정보를 추측하거나 복구하려 하지 마세요.
"""


def _capture_demo_request(
    context: ProxyContext | None,
    body: dict[str, Any],
) -> None:
    """시연 모드에서만 실제 전송할 요청 본문을 보관한다."""
    if context is not None and get_settings().demo_mode:
        context.upstream_request_body = copy.deepcopy(body)


async def _guard_l7_stream(
    context: ProxyContext,
    source: AsyncIterable[str],
) -> AsyncGenerator[str, None]:
    """실제 요청·응답 스트리밍 중 발생하는 오류를 기록한다."""
    started = perf_counter()
    try:
        async for chunk in source:
            yield chunk
    except Exception:
        context.status = "failed"
        context.error = "L7_STREAM_FAILED"
        raise
    finally:
        context.latency_ms["L7_stream"] = round((perf_counter() - started) * 1000, 3)


async def call_gemini_l7(context: ProxyContext) -> ProxyContext:
    """가명화된 요청을 벤더별 응답 스트림에 연결한다."""
    if context.status != "success":
        return context

    if context.parsed_request is None:
        context.status = "failed"
        context.error = "L7_PARSED_REQUEST_MISSING"
        return context

    if not context.reconstructed_body:
        context.status = "failed"
        context.error = "L7_RECONSTRUCTED_BODY_MISSING"
        return context

    try:
        vendor = context.parsed_request.vendor
        body = copy.deepcopy(context.reconstructed_body)

        # L2에서 사용한 모델을 실제 요청에도 명시한다.
        body["model"] = context.parsed_request.model

        key_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "CLAUDE_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }

        key_name = key_names.get(vendor)
        if key_name is None:
            context.status = "failed"
            context.error = "L7_UNSUPPORTED_VENDOR"
            return context

        api_key = os.getenv(key_name, "").strip()
        if not api_key:
            context.status = "failed"
            context.error = "L7_API_KEY_MISSING"
            return context

        _inject_system_prompt(vendor, body)

        source: AsyncIterable[str]

        if vendor == "openai":
            source = _stream_openai(body, api_key, context)
        elif vendor == "anthropic":
            source = _stream_claude(body, api_key, context)
        else:
            source = _stream_gemini(body, api_key, context)

        context.llm_raw_response = _guard_l7_stream(
            context,
            source,
        )

    except Exception:
        context.status = "failed"
        context.error = "L7_REQUEST_FAILED"

    return context


def _inject_system_prompt(
    vendor: str,
    body: dict[str, Any],
) -> None:
    """기존 지시를 유지하면서 프록시 지시를 추가한다."""
    if vendor == "openai":
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise ValueError("messages must be a list")

        messages.insert(
            0,
            {
                "role": "system",
                "content": PRIVACY_SYSTEM_SKILL,
            },
        )

    elif vendor == "anthropic":
        existing = body.get("system")

        if existing is None:
            body["system"] = PRIVACY_SYSTEM_SKILL
        elif isinstance(existing, str):
            body["system"] = PRIVACY_SYSTEM_SKILL + "\n\n" + existing
        elif isinstance(existing, list):
            body["system"] = [
                {
                    "type": "text",
                    "text": PRIVACY_SYSTEM_SKILL,
                },
                *existing,
            ]
        else:
            raise ValueError("unsupported system format")

    elif vendor == "gemini":
        existing = body.get("systemInstruction")

        if existing is None:
            body["systemInstruction"] = {
                "parts": [{"text": PRIVACY_SYSTEM_SKILL}],
            }
        elif isinstance(existing, dict):
            parts = existing.get("parts", [])
            if not isinstance(parts, list):
                raise ValueError("system parts must be a list")

            existing["parts"] = [
                {"text": PRIVACY_SYSTEM_SKILL},
                *parts,
            ]
        else:
            raise ValueError("unsupported system instruction")


async def _iter_sse_data(
    response: httpx.Response,
) -> AsyncGenerator[str, None]:
    """SSE 이벤트의 data 줄을 모아 반환한다."""
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue

        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)

    if data_lines:
        yield "\n".join(data_lines)


def _decode_event(data: str) -> dict[str, Any]:
    """응답 이벤트를 해석하고 벤더 오류를 확인한다."""
    event = json.loads(data)

    if not isinstance(event, dict):
        raise ValueError("unexpected upstream event")

    if "error" in event or event.get("type") == "error":
        raise RuntimeError("upstream error event")

    return event


async def _stream_openai(
    body: dict[str, Any],
    api_key: str,
    context: ProxyContext | None = None,
) -> AsyncGenerator[str, None]:
    """OpenAI 응답에서 텍스트 청크를 읽는다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body["stream"] = True
    _capture_demo_request(context, body)

    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=body,
        ) as response,
    ):
        response.raise_for_status()

        async for data in _iter_sse_data(response):
            if data.strip() == "[DONE]":
                break

            event = _decode_event(data)
            choices = event.get("choices", [])

            # 사용량 알림 등 텍스트가 없는 이벤트는 건너뛴다.
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            text = delta.get("content")

            if isinstance(text, str) and text:
                yield text


async def _stream_claude(
    body: dict[str, Any],
    api_key: str,
    context: ProxyContext | None = None,
) -> AsyncGenerator[str, None]:
    """Claude 응답에서 텍스트 청크를 읽는다."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body["stream"] = True
    _capture_demo_request(context, body)

    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
        ) as response,
    ):
        response.raise_for_status()

        async for data in _iter_sse_data(response):
            event = _decode_event(data)
            event_type = event.get("type")

            if event_type == "message_stop":
                break

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text")

                if isinstance(text, str) and text:
                    yield text


async def _stream_gemini(
    body: dict[str, Any],
    api_key: str,
    context: ProxyContext | None = None,
) -> AsyncGenerator[str, None]:
    """Gemini 응답에서 텍스트 청크를 읽는다."""
    # 모델은 URL에 지정하고 요청 본문에서는 제거한다.
    model = body.pop("model")
    if not isinstance(model, str) or not model:
        raise ValueError("model is required")

    if model.startswith("models/"):
        model = model[len("models/") :]

    body.pop("stream", None)
    _capture_demo_request(context, body)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"

    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream(
            "POST",
            url,
            params={"alt": "sse"},
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=body,
        ) as response,
    ):
        response.raise_for_status()

        async for data in _iter_sse_data(response):
            event = _decode_event(data)
            candidates = event.get("candidates", [])

            if not candidates:
                continue

            content = candidates[0].get("content", {})
            for part in content.get("parts", []):
                text = part.get("text")
                if isinstance(text, str) and text:
                    yield text
