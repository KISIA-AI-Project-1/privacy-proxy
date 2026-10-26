"""앵커 윈도우 매칭 — recognizers 공용 인프라.

``l4/ner/bio.py`` 와 같은 원칙: torch/transformers를 import하지 않는다. 문자열
거리 계산만으로 동작하고, 이 로직만 따로 테스트할 수 있어야 한다.

회사별 식별자 형식(자릿수 등)은 각 기업이 비공개로 관리해 공식 출처가 없다.
그래서 형식이 아니라 **문맥 키워드(앵커)** 로 판별한다 — "주문번호 12345" 의
"주문번호" 가 앵커다.
"""

from __future__ import annotations

from typing import NamedTuple


class AnchorHit(NamedTuple):
    """선택된 앵커. ``start``/``end`` 는 ``text`` 기준 반개구간 좌표."""

    distance: int
    text: str
    start: int
    end: int


def find_anchor(
    text: str,
    span_start: int,
    span_end: int,
    anchors: list[str],
    window: int = 25,
) -> AnchorHit | None:
    """span 주변 ``window`` 문자 안에서 가장 가까운 앵커 하나.

    앞쪽 앵커는 끝에서 span 시작까지, 뒤쪽 앵커는 span 끝에서 앵커 시작까지를
    거리로 잰다. 동률이면 앞쪽 앵커, 그다음 더 긴 앵커 순으로 고른다. 한국어
    CS 문장은 "주문번호 12345" 처럼 키워드가 값 앞에 오는 게 보통이다.
    앵커가 없으면 ``None``.
    """
    lo = max(0, span_start - window)
    left = text[lo:span_start]
    right = text[span_end : span_end + window]

    best: tuple[int, int, int, AnchorHit] | None = None
    for anchor in anchors:
        # 앞쪽: 여러 번 나오면 span에 가장 가까운(가장 오른쪽) 것을 쓴다.
        pos = left.rfind(anchor)
        if pos != -1:
            dist = len(left) - pos - len(anchor)
            hit = AnchorHit(dist, anchor, lo + pos, lo + pos + len(anchor))
            key = (dist, 0, -len(anchor), hit)
            if best is None or key[:3] < best[:3]:
                best = key
        # 뒤쪽: span 바로 뒤부터의 오프셋이 곧 거리다.
        pos = right.find(anchor)
        if pos != -1:
            hit = AnchorHit(pos, anchor, span_end + pos, span_end + pos + len(anchor))
            key = (pos, 1, -len(anchor), hit)
            if best is None or key[:3] < best[:3]:
                best = key

    return best[3] if best else None


def has_anchor(
    text: str,
    span_start: int,
    span_end: int,
    anchors: list[str],
    window: int = 25,
) -> tuple[bool, int]:
    """``find_anchor`` 의 ``(발견 여부, 거리)`` 형태. 없으면 ``(False, window + 1)``."""
    hit = find_anchor(text, span_start, span_end, anchors, window)
    return (True, hit.distance) if hit else (False, window + 1)


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
