"""건강·성생활 민감정보 탐지 — 본인 상태 진술(2번) + 구매 맥락(3번)."""

from l4.sensitive.engine import find_state
from l4.sensitive.purchase import find_purchase
from privacy_proxy.schemas import DetectedPII


def find_sensitive(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """2번+3번 합본. 상품 스팬과 겹치는 2번 스팬은 유지하고 그 상품을 버린다."""
    state = find_state(text, segment_id)
    purchase = find_purchase(text, segment_id, [(r.start_idx, r.end_idx) for r in state])
    return sorted(state + purchase, key=lambda r: r.start_idx)


__all__ = ["find_sensitive"]
