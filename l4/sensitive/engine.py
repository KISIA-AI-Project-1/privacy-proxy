"""본인 상태 진술 탐지 엔진 — 카테고리 공용.

사전어(질병·상태어, 제품유형어) 단독으로는 방출하지 않는다. 같은 문장에
서술 프레임이 있을 때만 방출한다. 공백을 제거한 문장에서 매칭하고 원문
좌표로 되돌린다. 프레임 거리는 ``recognizers/context.py`` 의 ``has_anchor``/
``score`` 를 그대로 쓴다.

구매 프레임("탈모 샴푸 정기배송")은 여기서 방출하지 않는다(``purchase.py`` 몫).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import yaml

from l4.recognizers.context import has_anchor, score
from l4.sensitive.health.guards import GUARDS as _HEALTH_GUARDS
from l4.sensitive.sex_life.guards import GUARDS as _SEX_LIFE_GUARDS
from privacy_proxy.schemas import DetectedPII, DetectionTier, EntityType

_BASE_SCORE = 0.6
_WINDOW = 25

# 프레임 이름 → (리터럴 목록, 창). stage/doc 외 이름은 용어 주변 창 안 어디서든.
_CONSUME = ("복용중", "복용하고", "복용했", "먹고있", "먹는중", "먹었")
_FRAMES: dict[str, tuple[tuple[str, ...], int]] = {
    "state": (
        (
            "있어",
            "잇어",
            "있습",
            "잇습",
            "있는데",
            "있다",
            "있음",
            "앓",
            "진단",
            "치료중",
            "치료받",
            "재발",
            "수술",
            "판정",
            "투병",
            "입원",
            "걸렸",
            "걸려",
            "시달",
            *_CONSUME,
        ),
        _WINDOW,
    ),
    "doc": (("첨부", "제출", "보내", "올렸", "드릴"), _WINDOW),
    "use": (("사용중", "사용하고", "사용했", "쓰고있", "쓰는중"), _WINDOW),
    "consume": (_CONSUME, _WINDOW),
    "stage": (("중", "했", "예정"), 2),  # 용어 바로 뒤(거리 0)에서만 인정
}
# 용어 바로 뒤에 붙는 광고 문구 — 복용 프레임이 같이 있어야 양성
_AD_MARKERS = ("에좋", "에도움", "에효과", "예방", "개선", "케어")

_DIR = Path(__file__).parent
_BOUNDARY = re.compile(r"(?<![.\d])\.(?![.\d])|[!?。\n]")  # 소수점·말줄임표는 경계 아님


def _squash(text: str, base: int = 0) -> tuple[str, list[int]]:
    """공백 제거 + 소문자. 반환 문자열 각 글자의 원문 인덱스를 함께 돌려준다."""
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        for c in ch.lower():
            chars.append(c)
            idx.append(base + i)
    return "".join(chars), idx


class _Category:
    def __init__(self, name: str, entity_type: EntityType, guards: tuple[str, ...]) -> None:
        entries = yaml.safe_load((_DIR / name / "lexicon.yaml").read_text(encoding="utf-8"))
        self.entity_type = entity_type
        self.guards = guards
        self.frames = {_squash(e["term"])[0]: e.get("frame", "state") for e in entries}
        terms = sorted(self.frames, key=len, reverse=True)  # 같은 시작이면 긴 용어 우선
        self.pattern = re.compile("|".join(map(re.escape, terms)))


_CATEGORIES = (
    _Category("health", EntityType.SENSITIVE_HEALTH, _HEALTH_GUARDS),
    _Category("sex_life", EntityType.SENSITIVE_SEX_LIFE, _SEX_LIFE_GUARDS),
)


def _sentences(text: str) -> Iterator[tuple[int, int]]:
    start = 0
    for m in _BOUNDARY.finditer(text):
        yield start, m.start()
        start = m.end()
    yield start, len(text)


def _scan(text: str, cat: _Category) -> list[tuple[int, int, float]]:
    hits: list[tuple[int, int, float]] = []
    for s, e in _sentences(text):
        sq, idx = _squash(text[s:e], s)
        for m in cat.pattern.finditer(sq):
            a, b = m.span()
            if any(
                g.start() < b and a < g.end()
                for guard in cat.guards
                for g in re.finditer(re.escape(guard), sq)
            ):
                continue
            frame = cat.frames[m.group()]
            if frame == "state" and any(sq.startswith(k, b) for k in _AD_MARKERS):
                frame = "consume"
            anchors, window = _FRAMES[frame]
            found, distance = has_anchor(sq, a, b, list(anchors), window)
            if not found or (frame == "stage" and distance):
                continue
            hits.append((idx[a], idx[b - 1] + 1, score(_BASE_SCORE, distance, window)))
    return hits


def find_state(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """건강·성생활 본인 상태 진술(2번). 겹치는 span은 합치고, 카테고리가 갈리면 건강."""
    hits = sorted(
        (a, b, cat.entity_type, conf) for cat in _CATEGORIES for a, b, conf in _scan(text, cat)
    )
    merged: list[tuple[int, int, EntityType, float]] = []
    for a, b, t, conf in hits:
        if merged and a < merged[-1][1]:
            pa, pb, pt, pc = merged[-1]
            merged[-1] = (
                pa,
                max(pb, b),
                t if t == pt else EntityType.SENSITIVE_HEALTH,
                max(pc, conf),
            )
        else:
            merged.append((a, b, t, conf))
    return [
        DetectedPII(
            entity_type=t,
            original_value=text[a:b],
            normalized=text[a:b],
            start_idx=a,
            end_idx=b,
            confidence=conf,
            segment_id=segment_id,
            tier=DetectionTier.RULE_ANCHORED,
            source=f"L4_{t.value}",
        )
        for a, b, t, conf in merged
    ]
