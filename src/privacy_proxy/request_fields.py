"""L2 전송 필드 허용 목록.

어댑터는 원본 body를 통째로 복사하고 텍스트 세그먼트만 교체한다. 그래서 세그먼트로
추출하지 않은 필드(``user``, ``metadata``, message의 ``name`` 등)는 탐지 없이 그대로
외부 LLM으로 나간다. 이 모듈은 "막을 것만 나열"하는 대신 **허용한 것만 통과**시킨다.

허용 규칙
- 최상위 키는 벤더별 허용 목록에 있어야 한다.
- 텍스트가 실릴 수 있는 곳(``messages[*].content``, ``contents[*].parts[*].text``)은
  L3~L6이 처리하는 세그먼트 경로이므로 **값은 보지 않고 구조(문자열인지, 다른 키가 없는지)만**
  확인한다.
- 그 밖의 옵션은 숫자/불리언만 허용한다. 문자열이 들어갈 수 있는 필드(``stop``, ``user``,
  ``metadata`` 등)는 탐지·치환 경로가 없으므로 허용하지 않는다.
- 위반 시 **필드 경로만** 돌려준다. 값은 로그나 오류에 남기지 않는다.
"""

import math
from typing import Any

_NUMBER = (int, float)

# 값이 숫자(불리언 제외)인 옵션
_OPENAI_NUMERIC = frozenset(
    {
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "n",
        "presence_penalty",
        "frequency_penalty",
        "seed",
    }
)
_CLAUDE_NUMERIC = frozenset({"max_tokens", "temperature", "top_p", "top_k"})
_GEMINI_CONFIG_NUMERIC = frozenset(
    {"temperature", "topP", "topK", "maxOutputTokens", "candidateCount"}
)

_CHAT_ROLES = frozenset({"user", "assistant", "system", "developer"})
_GEMINI_ROLES = frozenset({"user", "model"})
_CHAT_MESSAGE_KEYS = frozenset({"role", "content"})
_GEMINI_CONTENT_KEYS = frozenset({"role", "parts"})


def _is_number(value: Any) -> bool:
    """불리언과 NaN/Infinity는 숫자 옵션으로 인정하지 않는다(int는 크기와 무관하게 허용)."""
    if isinstance(value, bool) or not isinstance(value, _NUMBER):
        return False
    return isinstance(value, int) or math.isfinite(value)


def _check_numeric_options(
    body: dict[str, Any], numeric_keys: frozenset[str], base_keys: frozenset[str]
) -> list[str]:
    problems: list[str] = []
    for key, value in body.items():
        if key in base_keys:
            continue
        if key == "stream":
            if not isinstance(value, bool):
                problems.append("stream")
        elif key in numeric_keys:
            if not _is_number(value):
                problems.append(key)
        else:
            problems.append(key)
    return problems


def _check_chat_messages(messages: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(messages, list) or not messages:
        return ["messages"]
    for idx, message in enumerate(messages):
        if not isinstance(message, dict):
            problems.append(f"messages[{idx}]")
            continue
        for key in message:
            if key not in _CHAT_MESSAGE_KEYS:
                problems.append(f"messages[{idx}].{key}")
        if message.get("role", "user") not in _CHAT_ROLES:
            problems.append(f"messages[{idx}].role")
        # 문자열이 아닌 content(블록 리스트 등)는 L2가 세그먼트로 뽑지 못한다.
        # 파이프라인의 기존 검사에만 기대지 않도록 여기서도 막는다(이중 방어).
        if not isinstance(message.get("content"), str):
            problems.append(f"messages[{idx}].content")
    return problems


def _check_gemini_contents(contents: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(contents, list) or not contents:
        return ["contents"]
    for idx, content in enumerate(contents):
        if not isinstance(content, dict):
            problems.append(f"contents[{idx}]")
            continue
        for key in content:
            if key not in _GEMINI_CONTENT_KEYS:
                problems.append(f"contents[{idx}].{key}")
        if content.get("role", "user") not in _GEMINI_ROLES:
            problems.append(f"contents[{idx}].role")
        # parts 안쪽도 확인한다: 각 part는 {"text": <str>} 하나뿐이어야 한다.
        # (파이프라인에도 같은 검사가 있지만, 이 모듈만으로 허용 목록이 완결되게 한다.)
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            problems.append(f"contents[{idx}].parts")
            continue
        for p_idx, part in enumerate(parts):
            if not isinstance(part, dict):
                problems.append(f"contents[{idx}].parts[{p_idx}]")
                continue
            problems.extend(
                f"contents[{idx}].parts[{p_idx}].{key}" for key in part if key != "text"
            )
            if not isinstance(part.get("text"), str):
                problems.append(f"contents[{idx}].parts[{p_idx}].text")
    return problems


def find_unsupported_fields(vendor: str, body: dict[str, Any]) -> list[str]:
    """허용 목록 밖의 필드 경로를 돌려준다. 비어 있으면 그대로 전송해도 된다.

    ``model``과 메시지 본문은 각각 L1 모델 허용 목록·L3~L6 세그먼트 경로가 담당한다.
    """
    if not isinstance(body, dict):
        return ["<body>"]

    if vendor == "openai":
        problems = _check_numeric_options(body, _OPENAI_NUMERIC, frozenset({"model", "messages"}))
        problems.extend(_check_chat_messages(body.get("messages")))
    elif vendor == "anthropic":
        problems = _check_numeric_options(body, _CLAUDE_NUMERIC, frozenset({"model", "messages"}))
        problems.extend(_check_chat_messages(body.get("messages")))
    elif vendor == "gemini":
        problems = []
        for key, value in body.items():
            if key in {"model", "contents"}:
                continue
            if key == "stream":
                if not isinstance(value, bool):
                    problems.append("stream")
            elif key == "generationConfig":
                if not isinstance(value, dict):
                    problems.append("generationConfig")
                    continue
                for sub_key, sub_value in value.items():
                    if sub_key not in _GEMINI_CONFIG_NUMERIC or not _is_number(sub_value):
                        problems.append(f"generationConfig.{sub_key}")
            else:
                problems.append(key)
        problems.extend(_check_gemini_contents(body.get("contents")))
    else:
        return ["<vendor>"]

    return sorted(set(problems))
