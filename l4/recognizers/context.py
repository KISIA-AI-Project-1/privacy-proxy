"""앵커 윈도우 매칭 — recognizers 공용 인프라.

``l4/ner/bio.py`` 와 같은 원칙: torch/transformers를 import하지 않는다. 문자열
거리 계산만으로 동작하고, 이 로직만 따로 테스트할 수 있어야 한다.

회사별 식별자 형식(자릿수 등)은 각 기업이 비공개로 관리해 공식 출처가 없다.
그래서 형식이 아니라 **문맥 키워드(앵커)** 로 판별한다 — "주문번호 12345" 의
"주문번호" 가 앵커다.
"""

from __future__ import annotations


def has_anchor(
    text: str,
    span_start: int,
    span_end: int,
    anchors: list[str],
    window: int = 25,
) -> tuple[bool, int]:
    """span 주변 ``window`` 문자 안에 앵커 키워드가 있는지.

    앞뒤 양방향을 보고 가장 가까운 앵커까지의 문자 거리를 잰다. 한국어 CS
    문장은 "주문번호 12345" 처럼 키워드가 값 앞에 오는 게 보통이라, 앞/뒤가
    같은 거리면 앞쪽이 선택된다(앞쪽을 먼저 훑는다).

    Returns:
        ``(발견 여부, 가장 가까운 앵커까지 거리)``. 없으면 ``(False, window + 1)``.
    """
    left = text[max(0, span_start - window) : span_start]
    right = text[span_end : span_end + window]

    best = window + 1
    for anchor in anchors:
        # 앞쪽: 여러 번 나오면 span에 가장 가까운(가장 오른쪽) 것을 쓴다.
        pos = left.rfind(anchor)
        if pos != -1:
            best = min(best, len(left) - pos - len(anchor))
        # 뒤쪽: span 바로 뒤부터의 오프셋이 곧 거리다.
        pos = right.find(anchor)
        if pos != -1:
            best = min(best, pos)

    return (best <= window, best if best <= window else window + 1)


def score(
    base_score: float,
    distance: int,
    window: int = 25,
    bonus: float = 0.35,
) -> float:
    """confidence 산정 — 초기 임의값. 체크섬·모델 확률 같은 근거가 없다.

    앵커가 값에 붙어 있을수록(distance ↓) base_score 위로 최대 ``bonus`` 만큼
    올린다. [0, 1] 로 자른다 — confidence는 정의상 확률 범위이고, 이 값이
    그대로 L5 위험도 계산에 들어가므로 1을 넘기면 안 된다.
    """
    raw = base_score + bonus * (1 - distance / window)
    return max(0.0, min(1.0, raw))
