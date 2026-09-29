import copy
import os
import re
from typing import Any

from fastapi import Header, HTTPException

from privacy_proxy.schemas import ParsedRequest, TextSegment, UserContext

# =============================================================
# [L1: 인증·인가 모듈]
# =============================================================
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "example-proxy-key")


async def get_current_user(authorization: str = Header(default="")) -> UserContext:
    """
    [L1 출입증 검사기]
    - Authorization: Bearer <키> 형식 확인
    - 키가 없거나 틀리면 401 Unauthorized 에러 발생
    - 통과 시 요청자 정보(UserContext) 반환
    """
    expected = f"Bearer {PROXY_API_KEY}"
    print(f"서버가 기대하는 값: [{expected}]")
    print(f"실제 입력받은 값: [{authorization}]")

    if not authorization or authorization != expected:
        raise HTTPException(
            status_code=401,
            detail="Invalid proxy credential",
        )

    # 인증 통과 시 사용자 컨텍스트 발급
    return UserContext(
        user_id="poc-user",
        department="poc-team",
        role="developer",
        allowed_models=["gpt-5", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "gemini-1.5-pro"],
        restore_level="default",
    )


# =============================================================
# [L2: 요청 파싱 및 재조립 모듈 - 멀티 벤더 지원]
# =============================================================


# 1. OpenAI (ChatGPT 규격) 어댑터
class OpenAIAdapter:
    @staticmethod
    def parse(body: dict[str, Any]) -> ParsedRequest:
        if "messages" not in body or not isinstance(body["messages"], list):
            raise HTTPException(
                status_code=400, detail="Invalid JSON format: 'messages' array required"
            )

        model = body.get("model", "gpt-4o")
        segments: list[TextSegment] = []

        for idx, msg in enumerate(body["messages"]):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                segments.append(
                    TextSegment(
                        segment_id=f"seg-{idx + 1}",
                        path=f"messages[{idx}].content",
                        role=msg.get("role", "user"),
                        text=content,
                    )
                )

        return ParsedRequest(
            vendor="openai",
            model=model,
            segments=segments,
            original_body=body,
        )

    @staticmethod
    def rebuild(
        parsed_request: ParsedRequest, processed_segments: list[TextSegment]
    ) -> dict[str, Any]:
        rebuilt_body = copy.deepcopy(parsed_request.original_body)
        segment_map = {seg.segment_id: seg.text for seg in processed_segments}

        for seg in parsed_request.segments:
            new_text = segment_map.get(seg.segment_id, seg.text)
            match = re.match(r"messages\[(\d+)\]\.content", seg.path)
            if match:
                idx = int(match.group(1))
                rebuilt_body["messages"][idx]["content"] = new_text

        return rebuilt_body


# 2. Anthropic (Claude 규격) 어댑터
class ClaudeAdapter:
    @staticmethod
    def parse(body: dict[str, Any]) -> ParsedRequest:
        if "messages" not in body or not isinstance(body["messages"], list):
            raise HTTPException(
                status_code=400, detail="Invalid JSON format: 'messages' array required"
            )

        model = body.get("model", "claude-3-5-sonnet")
        segments: list[TextSegment] = []

        for idx, msg in enumerate(body["messages"]):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                segments.append(
                    TextSegment(
                        segment_id=f"seg-{idx + 1}",
                        path=f"messages[{idx}].content",
                        role=msg.get("role", "user"),
                        text=content,
                    )
                )

        return ParsedRequest(
            vendor="anthropic",
            model=model,
            segments=segments,
            original_body=body,
        )

    @staticmethod
    def rebuild(
        parsed_request: ParsedRequest, processed_segments: list[TextSegment]
    ) -> dict[str, Any]:
        rebuilt_body = copy.deepcopy(parsed_request.original_body)
        segment_map = {seg.segment_id: seg.text for seg in processed_segments}

        for seg in parsed_request.segments:
            new_text = segment_map.get(seg.segment_id, seg.text)
            match = re.match(r"messages\[(\d+)\]\.content", seg.path)
            if match:
                idx = int(match.group(1))
                rebuilt_body["messages"][idx]["content"] = new_text

        return rebuilt_body


# 3. Google (Gemini 규격) 어댑터
class GeminiAdapter:
    @staticmethod
    def parse(body: dict[str, Any]) -> ParsedRequest:
        if "contents" not in body or not isinstance(body["contents"], list):
            raise HTTPException(
                status_code=400, detail="Invalid JSON format: 'contents' array required"
            )

        model = body.get("model", "gemini-1.5-pro")
        segments: list[TextSegment] = []

        for c_idx, content in enumerate(body["contents"]):
            role = content.get("role", "user")
            for p_idx, part in enumerate(content.get("parts", [])):
                text = part.get("text", "")
                if isinstance(text, str) and text.strip():
                    segments.append(
                        TextSegment(
                            segment_id=f"seg-{c_idx + 1}-{p_idx + 1}",
                            path=f"contents[{c_idx}].parts[{p_idx}].text",
                            role=role,
                            text=text,
                        )
                    )

        return ParsedRequest(
            vendor="gemini",
            model=model,
            segments=segments,
            original_body=body,
        )

    @staticmethod
    def rebuild(
        parsed_request: ParsedRequest, processed_segments: list[TextSegment]
    ) -> dict[str, Any]:
        rebuilt_body = copy.deepcopy(parsed_request.original_body)
        segment_map = {seg.segment_id: seg.text for seg in processed_segments}

        for seg in parsed_request.segments:
            new_text = segment_map.get(seg.segment_id, seg.text)
            match = re.match(r"contents\[(\d+)\]\.parts\[(\d+)\]\.text", seg.path)
            if match:
                c_idx, p_idx = int(match.group(1)), int(match.group(2))
                rebuilt_body["contents"][c_idx]["parts"][p_idx]["text"] = new_text

        return rebuilt_body


# 4. [라우터] 들어온 JSON 모양을 보고 적절한 벤더 어댑터를 찾아주는 판별기
class AdapterRouter:
    @staticmethod
    def get_adapter(body: dict[str, Any]) -> Any:
        if "contents" in body:
            return GeminiAdapter
        elif "messages" in body:
            model = body.get("model", "").lower()
            if "claude" in model:
                return ClaudeAdapter
            return OpenAIAdapter
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported request format: Cannot identify LLM vendor (OpenAI, Claude, Gemini).",
            )
