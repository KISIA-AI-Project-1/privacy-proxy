"""문맥 키워드(앵커) 기반 민감정보 탐지 — 4종(건강/종교/가족/재정).

``l4/recognizers/``와 달리 형식 정규식이 없다 — 앵커 단어의 등장 자체가
탐지 대상이다. 그래서 confidence가 낮고(고정값) tier도 가장 낮은
``CANDIDATE``다: 최종 판단은 L5로 넘긴다.
"""

from l4.sensitive.recognizers import (
    find_sensitive_family,
    find_sensitive_financial,
    find_sensitive_health,
    find_sensitive_religion,
)

__all__ = [
    "find_sensitive_family",
    "find_sensitive_financial",
    "find_sensitive_health",
    "find_sensitive_religion",
]
