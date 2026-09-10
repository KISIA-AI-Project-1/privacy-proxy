import os
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

## CRITICAL RULES (절대 규칙)
- 입력된 텍스트에 포함된 가짜 이름, 전화번호, 이메일 등의 가명화된 정보는 시스템에서 임의로 치환된 것입니다.
- 답변을 생성할 때, 사용자가 보낸 가짜 정보(예: 홍길동님)를 그대로 인용하거나 자연스럽게 사용하여 문맥의 일관성을 유지하십시오.
- 실제 개인정보를 유추하거나 원래의 진짜 정보가 무엇인지 언급하거나 되묻지 마십시오.
- 오직 전달받은 텍스트의 맥락 안에서만 안전하게 응답하십시오.
"""


async def call_gemini_l7(context: ProxyContext) -> ProxyContext:
    """
    [L7: LLM 중계 레이어]
    가명화가 완료된 재조립 JSON에 시스템 프롬프트를 주입하고 벤더 서버로 전송합니다.
    """
    if context.status != "success" or not context.parsed_request:
        return context

    vendor = context.parsed_request.vendor
    body = context.reconstructed_body

    _inject_system_prompt(vendor, body)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if vendor == "openai":
                context.llm_raw_response = await _call_openai(client, body)
            elif vendor == "anthropic":
                context.llm_raw_response = await _call_claude(client, body)
            elif vendor == "gemini":
                context.llm_raw_response = await _call_gemini(client, body)
            else:
                raise ValueError(f"지원하지 않는 벤더입니다: {vendor}")

        except Exception as e:
            context.status = "failed"
            context.error = f"L7 LLM Request Error: {e!s}"

    return context


def _inject_system_prompt(vendor: str, body: dict[str, Any]) -> None:
    """각 LLM 벤더의 JSON 구조에 맞춰 시스템 프롬프트를 안전하게 삽입합니다."""
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


async def _call_openai(client: httpx.AsyncClient, body: dict[str, Any]) -> str:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    response = await client.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=body,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"])


async def _call_claude(client: httpx.AsyncClient, body: dict[str, Any]) -> str:
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    response = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=body,
    )
    response.raise_for_status()
    return str(response.json()["content"][0]["text"])


async def _call_gemini(client: httpx.AsyncClient, body: dict[str, Any]) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{body.get('model', 'gemini-1.5-pro')}:generateContent?key={GEMINI_API_KEY}"
    response = await client.post(
        url,
        headers={"Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    return str(response.json()["candidates"][0]["content"]["parts"][0]["text"])
