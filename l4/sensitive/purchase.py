"""구매 맥락 탐지 — 민감 상품(PRODUCT_ITEM)과 반복 구매 단서(PURCHASE_PATTERN).

질병·상태어와 성생활 제품유형어는 2번 ``lexicon.yaml`` 을 그대로 쓴다. 상품은
같은 문장에 구매 맥락어가 있을 때만, 단서는 같은 문장에 상품이 있을 때만
방출한다. 단서와 상품의 짝은 방출 여부를 정하는 데만 쓰고 출력하지 않는다.
"""

from __future__ import annotations

import re

from l4.recognizers.context import has_anchor, score
from l4.sensitive.engine import _CATEGORIES, _sentences, _squash
from privacy_proxy.schemas import DetectedPII, DetectionTier, EntityType

_BASE_SCORE = 0.6
_WINDOW = 25

_PRODUCT_TYPES = (
    "치료제", "영양제", "보충제", "보조제", "비타민", "샴푸", "크림", "앰플",
    "세럼", "패치", "스프레이", "젤", "약", "키트", "테스트기",
)  # fmt: skip
_MODIFIERS = (
    "개선용", "치료용", "예방용", "관리용", "완화용", "전용", "에좋은",
    "케어", "개선", "치료", "예방", "관리", "완화", "보조", "용",
)  # fmt: skip
_CONTEXT = (
    "샀", "구매", "주문", "시켜", "시킨", "배송", "정기", "결제", "환불",
    "반품", "교환", "재구매", "받았", "받고", "시켰", "구입", "신청",
)  # fmt: skip
# 강한 단서가 있으면 약한 단서(주기 표현)는 그 수식어로 보고 버린다
_STRONG = (
    "정기배송",
    "정기구독",
    "정기결제",
    "자동결제",
    "재구매",
    "재주문",
    "또주문",
    "다시주문",
    "추가주문",
)
_WEAK = (
    "매달", "매월", "매주", r"\d+개월째", r"\d+개월마다", r"\d+개월주기", r"\d+주마다",
    r"주\d+회", "떨어졌", "늘먹던", "먹던걸로", "지난달이랑", "똑같이",
)  # fmt: skip


def _alt(words: list[str] | tuple[str, ...], escape: bool = True) -> str:
    return "|".join(sorted((re.escape(w) if escape else w for w in words), key=len, reverse=True))


def _terms(keep: set[str] | None, drop: set[str]) -> list[str]:
    return [
        t
        for c in _CATEGORIES
        for t, f in c.frames.items()
        if f not in drop and (keep is None or f in keep)
    ]


_DISEASE = _alt(_terms(None, {"doc", "use"}))
_STANDALONE = _alt(_terms({"use"}, set()))
_DRUG = _alt(
    [t for t in _terms(None, {"doc", "use"}) if t.endswith("약")]
)  # 사후피임약 등 약 자체가 용어
_PRODUCT = re.compile(
    rf"(?:{_DRUG})|(?:{_DISEASE})(?:{_alt(_MODIFIERS)}){{0,2}}(?:{_alt(_PRODUCT_TYPES)})(?![속간])"
    rf"|{_STANDALONE}"
)
_STRONG_RE = re.compile(_alt(_STRONG, escape=False))
_WEAK_RE = re.compile(_alt(_WEAK, escape=False))
_GUARDS = tuple(g for c in _CATEGORIES for g in c.guards)
_COUNSELOR = re.compile(r"[ \t]*상담사[ \t]*:")


def _guarded(sq: str, a: int, b: int) -> bool:
    return any(
        a < g.end() and g.start() < b for w in _GUARDS for g in re.finditer(re.escape(w), sq)
    )


def _context_distance(text: str, sq: str, idx: list[int], a: int, b: int) -> int | None:
    found, distance = has_anchor(sq, a, b, list(_CONTEXT), _WINDOW)
    if found:
        return distance
    # 관형형 "산"은 상품 바로 앞(공백 1칸 이내)일 때만 구매 맥락
    before = text[max(0, idx[a] - 2) : idx[a]]
    return 0 if before.endswith("산") or before == "산 " else None


def _item(
    text: str, entity_type: EntityType, a: int, b: int, conf: float, segment_id: str
) -> DetectedPII:
    return DetectedPII(
        entity_type=entity_type,
        original_value=text[a:b],
        normalized=text[a:b],
        start_idx=a,
        end_idx=b,
        confidence=conf,
        segment_id=segment_id,
        tier=DetectionTier.RULE_ANCHORED,
        source=f"L4_SENSITIVE_{entity_type.value}",
    )


def find_purchase(
    text: str, segment_id: str = "seg-1", keep: list[tuple[int, int]] | None = None
) -> list[DetectedPII]:
    """PRODUCT_ITEM·PURCHASE_PATTERN. 문장 경계를 넘는 연결은 하지 않는다.

    ``keep`` 은 유지할 2번 스팬. 겹치는 상품은 버리고, 단서는 남은 상품 기준으로 판정한다.
    """
    out: list[DetectedPII] = []
    for s, e in _sentences(text):
        sq, idx = _squash(text[s:e], s)
        products: list[tuple[int, int]] = []
        for m in _PRODUCT.finditer(sq):
            a, b = m.span()
            distance = _context_distance(text, sq, idx, a, b)
            if distance is None or _guarded(sq, a, b):
                continue
            if any(idx[a] < kb and ka < idx[b - 1] + 1 for ka, kb in keep or ()):
                continue
            products.append((a, b))
            conf = score(_BASE_SCORE, distance, _WINDOW)
            out.append(
                _item(text, EntityType.PRODUCT_ITEM, idx[a], idx[b - 1] + 1, conf, segment_id)
            )
        if not products:
            continue
        clues = list(_STRONG_RE.finditer(sq)) or list(_WEAK_RE.finditer(sq))
        for m in clues:
            a, b = m.span()
            line_start = text.rfind("\n", 0, idx[a]) + 1
            if _COUNSELOR.match(text, line_start):
                continue
            gap = min(max(pa - b, a - pb, 0) for pa, pb in products)
            conf = score(_BASE_SCORE, min(gap, _WINDOW), _WINDOW)
            out.append(
                _item(text, EntityType.PURCHASE_PATTERN, idx[a], idx[b - 1] + 1, conf, segment_id)
            )
    return out
