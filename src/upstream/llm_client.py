import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from privacy_proxy.schemas import ProxyContext

# 환경변수에서 벤더별 API 키 로드
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

PRIVACY_SYSTEM_SKILL = """
# System Skill: Contextual Consistency with Pseudonymized Data
당신은 개인정보 보호 프록시(Privacy Proxy)를 거쳐 사용자와 소통하는 AI 어시스턴트입니다.
사용자의 입력 데이터는 프라이버시 보호를 위해 가짜 개인정보(예: 홍길동, 010-123-456 등)로 대체(가명화)되어 전달됩니다.

## (절대 규칙)
- 입력된 텍스트에 포함된 가짜 이름, 전화번호, 이메일 등의 가명화된 정보는 시스템에서 임의로 치환된 것입니다.
- 답변을 생성할 때, 사용자가 보낸 가짜 정보(예: 홍길동님)를 그대로 인용하거나 자연스럽게 사용하여 문맥의 일관성을 유지하십시오.
- 실제 개인정보를 유추하거나 원래의 진짜 정보가 무엇인지 언급하거나 되묻지 마십시오.
- 오직 전달받은 텍스트의 맥락 안에서만 안전하게 응답하십시오.
"""


async def call_gemini_l7(context: ProxyContext) -> ProxyContext:
    """
    [L7: LLM 중계 레이어]
    """
    if context.status != "success" or not context.parsed_request:
        return context

    vendor = context.parsed_request.vendor
    body = context.reconstructed_body

    _inject_system_prompt(vendor, body)

    try:
        if vendor == "openai":
            context.llm_raw_response = _stream_openai(body)
        elif vendor == "anthropic":
            context.llm_raw_response = _stream_claude(body)
        elif vendor == "gemini":
            context.llm_raw_response = _stream_gemini(body)
        else:
            raise ValueError(f"지원하지 않는 벤더입니다: {vendor}")

    except Exception as e:
        context.status = "failed"
        context.error = f"L7 LLM Request Error: {e!s}"

    return context


def _inject_system_prompt(vendor: str, body: dict[str, Any]) -> None:
    if vendor == "openai":
        messages = body.setdefault("messages", [])
        if not any(msg.get("role") == "system" for msg in messages):
            messages.insert(0, {"role": "system", "content": PRIVACY_SYSTEM_SKILL})

    elif vendor == "anthropic":
        if "system" not in body:
            body["system"] = PRIVACY_SYSTEM_SKILL

    elif vendor == "gemini":
        if "systemInstruction" not in body:
            body["systemInstruction"] = {
                "role": "system",
                "parts": [{"text": PRIVACY_SYSTEM_SKILL}],
            }


async def _stream_openai(body: dict[str, Any]) -> AsyncGenerator[str, None]:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    body["stream"] = True

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

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data_json = json.loads(data_str)
                    chunk = data_json["choices"][0]["delta"].get("content", "")
                    if chunk:
                        yield chunk
                except json.JSONDecodeError:
                    continue


async def _stream_claude(body: dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    [Claude API 전용 스트리밍 어댑터]
    """
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body["stream"] = True

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

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    data_json = json.loads(data_str)
                    if data_json.get("type") == "content_block_delta":
                        chunk = data_json["delta"].get("text", "")
                        if chunk:
                            yield chunk
                except json.JSONDecodeError:
                    continue


async def _stream_gemini(body: dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    [Gemini API 전용 스트리밍 어댑터]
    """
    model_name = body.get("model", "gemini-1.5-pro")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"

    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream(
            "POST",
            url,
            headers={"Content-Type": "application/json"},
            json=body,
        ) as response,
    ):
        response.raise_for_status()

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    data_json = json.loads(data_str)
                    chunk = data_json["candidates"][0]["content"]["parts"][0].get("text", "")
                    if chunk:
                        yield chunk

                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
