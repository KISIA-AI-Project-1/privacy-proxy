"""l4/text_normalize — 기대값은 손으로 쓴 하드코딩 값."""

import pytest
from l4.text_normalize import normalize_for_match


@pytest.mark.parametrize("ch", ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad"])
def test_invisible_becomes_space(ch: str) -> None:
    assert normalize_for_match(f"당{ch}뇨") == "당 뇨"


@pytest.mark.parametrize(
    "ch", ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212", "\ufe63"]
)
def test_hyphens_become_ascii(ch: str) -> None:
    assert normalize_for_match(f"010{ch}1234") == "010-1234"


def test_fullwidth_folded() -> None:
    assert normalize_for_match("\uff28\uff29\uff36 \u2460") == "HIV 1"


def test_compat_jamo_kept() -> None:
    assert normalize_for_match("\u3131\u3141\u318e") == "\u3131\u3141\u318e"


@pytest.mark.parametrize("ch", ["\u3231", "\u00bd", "\u2122"])
def test_multi_char_expansion_keeps_original(ch: str) -> None:
    assert normalize_for_match(ch) == ch


def test_length_preserved_and_later_coordinates_unchanged() -> None:
    text = "\u3231 당\u200b뇨 \u00bd \ufb01 \u2460"
    out = normalize_for_match(text)
    assert len(out) == len(text)
    assert out.index("뇨") == text.index("뇨")
