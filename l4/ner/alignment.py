"""조사 경계 중재 — NER span 끝에 딸려 들어간 조사를 떼어낸다.

``merge_bio_spans`` 다음에 붙는다. 서브워드 토크나이저가 이름과 조사를 한
토큰으로 묶으면(``##은이``) 모델이 그 안에서 경계를 낼 수 없어 span이
'송하은은'까지 늘어난다. 여기서 조사만 잘라 '송하은'으로 되돌린다.

판별 규칙:

- span 마지막 문자를 담은 **토큰의 길이**로 신뢰 여부를 가른다.
  - 길이 1  → 모델이 글자 단위로 독립 판단할 수 있었다 → 그대로 둔다.
  - 길이 2+ → 토큰이 여러 글자를 묶어 중간에서 못 끊었다 → 조사 대조.
- 조사 대조는 **마지막 토큰의 표면 텍스트만** 본다. span 전체를 훑으면
  '김하나'가 조사 '나'에 걸리는 식의 오탐이 난다.
- 받침 유무로 이형태가 갈리는 조사(은/는, 이/가 …)는 조사 앞 음절의 받침을
  확인한다. '가을'의 '을', '지은'의 '은'이 잘려나가는 것을 막는다.

L4는 recall 우선이다 — 이름 한 글자를 조사로 오인해 자르면 그게 곧 유출이라,
확신이 설 때만 자른다. 애매한 단음절 조사(의/도/만/에/로)는 목록에 안 넣는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from l4.ner.bio import Span

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3

# (조사, 앞 음절 받침 필요 여부). None = 받침 무관.
# 긴 것부터 매칭한다. 이형태 없는 다음절 조사는 이름 끝과 겹칠 일이 거의 없다.
# 호격 '아/야'는 이름 끝(민아·수아…)과 자주 겹쳐 뺐다.
_JOSA: tuple[tuple[str, bool | None], ...] = (
    ("으로부터", None),
    ("이라고", None),
    ("이라는", None),
    ("에게서", None),
    ("에게", None),
    ("한테", None),
    ("에서", None),
    ("께서", None),
    ("부터", None),
    ("까지", None),
    ("처럼", None),
    ("조차", None),
    ("마저", None),
    ("밖에", None),
    ("라고", None),
    ("라는", None),
    ("으로", None),
    ("께", None),
    ("이", True),
    ("가", False),
    ("은", True),
    ("는", False),
    ("을", True),
    ("를", False),
    ("과", True),
    ("와", False),
)


def _has_batchim(ch: str) -> bool:
    """한글 음절이 종성(받침)을 가지면 True. 한글이 아니면 False."""
    code = ord(ch) - _HANGUL_BASE
    return 0 <= code <= _HANGUL_LAST - _HANGUL_BASE and code % 28 != 0


def _josa_suffix_len(surface: str) -> int:
    """토큰 표면 텍스트 끝에 붙은 조사의 길이. 없으면 0."""
    for josa, needs_batchim in _JOSA:
        if not surface.endswith(josa):
            continue
        if needs_batchim is None:
            return len(josa)
        if len(surface) <= len(josa):
            continue  # 앞 음절이 이 토큰에 없어 받침 확인 불가 → 보류
        if _has_batchim(surface[-len(josa) - 1]) == needs_batchim:
            return len(josa)
    return 0


def _token_at(offsets: Sequence[Sequence[int]], pos: int) -> tuple[int, int] | None:
    """문자 위치 ``pos`` 를 덮는 토큰의 ``(start, end)``. 없으면 None."""
    for start, end in offsets:
        if start < end and start <= pos < end:
            return start, end
    return None


def arbitrate_josa(
    spans: Sequence[Span],
    offsets: Sequence[Sequence[int]],
    text: str,
) -> list[Span]:
    """span 끝에 딸려온 조사를 떼어낸다. 순서는 그대로 유지한다.

    Args:
        spans: ``merge_bio_spans`` 의 출력.
        offsets: 토큰별 ``(start, end)`` 문자 오프셋 (특수 토큰은 ``(0, 0)``).
        text: 원문. 잘라낸 뒤 span ``text`` 필드를 다시 채운다.
    """
    result: list[Span] = []
    for span in spans:
        token = _token_at(offsets, span.end - 1)
        if token is None or token[1] - token[0] <= 1:
            result.append(span)
            continue

        cut = _josa_suffix_len(text[token[0] : token[1]])
        if cut and span.end - cut > span.start:
            end = span.end - cut
            span = Span(span.start, end, span.entity_type, text[span.start : end])
        result.append(span)
    return result
