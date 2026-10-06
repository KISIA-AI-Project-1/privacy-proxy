"""매칭 전용 유니코드 정규화 — 문자 단위 치환이라 길이와 좌표가 항상 보존된다."""

import unicodedata

_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff\u00ad")
_HYPHENS = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe63")


def _normalize_char(ch: str) -> str:
    if ch in _INVISIBLE:
        return " "
    if ch in _HYPHENS:
        return "-"
    if "\u3131" <= ch <= "\u318e":  # 한글 호환 자모: NFKC가 초성 자모로 바꾸므로 제외
        return ch
    folded = unicodedata.normalize("NFKC", ch)
    return folded if len(folded) == 1 else ch  # ㈜·½·™ 같은 확장형은 원본 유지


def normalize_for_match(text: str) -> str:
    out = "".join(_normalize_char(ch) for ch in text)
    assert len(out) == len(text)  # noqa: S101
    return out
