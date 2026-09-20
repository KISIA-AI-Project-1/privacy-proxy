"""앵커 위치 → ``DetectedPII`` 방출 — 민감정보 4종.

``l4/recognizers/recognizers.py``와 전제가 다르다: 회사별 ID와 달리
민감정보는 애초에 검증 가능한 "형식"이 없다 — 문장에 특정 단어가 등장했다는
사실 자체가 신호다. 그래서 형식 정규식으로 후보를 좁히는 단계가 없고,
``find_anchor_spans``가 찾은 앵커 위치를 그대로 span으로 쓴다. 경계를
넓히거나 좁히는 판단(예: "아이가"의 문법적 범위)은 하지 않는다 — 앵커
표면형 그대로가 곧 ``original_value``다.

confidence는 앵커 거리 개념이 없어 카테고리 공통 고정값이다. tier가
``CANDIDATE``(가장 낮은 등급)인 이유: 형식 검증도 문맥 거리 가산도 없는
순수 어휘 매치라 정밀도가 가장 낮다 — 최종 판단을 L5로 넘기라는 신호로
의도적으로 가장 낮은 tier를 준다.

**주의 (시드는 그대로 반영, 필터링 안 함):** 일부 앵커는 이커머스 CS
문장에서 민감정보와 무관하게도 흔히 등장해 오탐 위험이 크다 — "장애"는
"배송 시스템 장애"·"네트워크 장애"처럼 고장을 뜻하는 CS 상투어에도 흔히
쓰이고, "아이가"/"남편이"/"아내가"는 단순 구매 후기("남편이 좋아해요")에도
흔하다. 경계를 확정하지 않는 설계 자체가 이런 오탐을 어느 정도 감수하는
전제라 시드를 그대로 반영했다 — 판단은 호출부(L5) 몫으로 미룬다. 실측은 W7.
"""

from __future__ import annotations

from l4.sensitive.anchors import ANCHORS
from l4.sensitive.context import find_anchor_spans
from privacy_proxy.schemas import DetectedPII, DetectionTier

# 임의 초기값, 카테고리 구분 없이 동일 — 앵커 거리 같은 차등 근거가 없다.
# TODO(W7): 합성 평가셋 실측 후 카테고리별 조정 여부 판단.
_CONFIDENCE = 0.4


def _emit(
    category: str, source: str, text: str, start: int, end: int, segment_id: str
) -> DetectedPII:
    value = text[start:end]
    return DetectedPII(
        entity_type=category,
        original_value=value,
        normalized=value,
        start_idx=start,
        end_idx=end,
        confidence=_CONFIDENCE,
        segment_id=segment_id,
        tier=DetectionTier.CANDIDATE,
        source=source,
    )


def _find_sensitive(category: str, source: str, text: str, segment_id: str) -> list[DetectedPII]:
    return [
        _emit(category, source, text, start, end, segment_id)
        for start, end, _ in find_anchor_spans(text, ANCHORS[category])
    ]


def find_sensitive_health(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_sensitive("SENSITIVE_HEALTH", "L4_SENSITIVE_HEALTH", text, segment_id)


def find_sensitive_religion(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_sensitive("SENSITIVE_RELIGION", "L4_SENSITIVE_RELIGION", text, segment_id)


def find_sensitive_family(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_sensitive("SENSITIVE_FAMILY", "L4_SENSITIVE_FAMILY", text, segment_id)


def find_sensitive_financial(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_sensitive("SENSITIVE_FINANCIAL", "L4_SENSITIVE_FINANCIAL", text, segment_id)
