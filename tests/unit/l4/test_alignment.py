"""조사 경계 중재 테스트.

서브워드 토크나이저가 이름과 조사를 한 토큰으로 묶어(``##은이``) span이
조사까지 늘어나는 경우를 되돌리는지 본다. 픽스처는 전부 가상의 이름이다.

offsets는 실제 KLUE-BERT 토크나이징을 손으로 옮긴 것이다:
``[CLS]``·``[SEP]`` 는 ``(0, 0)``, 나머지는 ``(start, end)`` 문자 오프셋.
"""

import pytest
from l4.ner.alignment import _has_batchim, _josa_suffix_len, arbitrate_josa
from l4.ner.bio import Span


def _arbitrate_one(text: str, offsets: list[tuple[int, int]], span: Span) -> Span:
    return arbitrate_josa([span], offsets, text)[0]


# ── 회귀: 조사가 마지막 토큰에 이름과 함께 묶인 경우 ──────────────────────


def test_송하은은_에서_주격조사_은을_뗀다() -> None:
    text = "송하은은"
    offsets = [(0, 0), (0, 2), (2, 4), (0, 0)]  # [CLS] 송하 ##은은 [SEP]
    span = Span(0, 4, "PS", "송하은은")

    assert _arbitrate_one(text, offsets, span) == Span(0, 3, "PS", "송하은")


def test_김지은이_에서_주격조사_이를_뗀다() -> None:
    text = "김지은이"
    offsets = [(0, 0), (0, 2), (2, 4), (0, 0)]  # [CLS] 김지 ##은이 [SEP]
    span = Span(0, 4, "PS", "김지은이")

    assert _arbitrate_one(text, offsets, span) == Span(0, 3, "PS", "김지은")


def test_다음절_조사도_뗀다() -> None:
    text = "김철수에게"
    offsets = [(0, 0), (0, 3), (3, 5), (0, 0)]  # [CLS] 김철수 ##에게 [SEP]
    span = Span(0, 5, "PS", "김철수에게")

    assert _arbitrate_one(text, offsets, span) == Span(0, 3, "PS", "김철수")


def test_받침_있는_이름_뒤_접속조사_과를_뗀다() -> None:
    text = "이서연과"
    offsets = [(0, 0), (0, 3), (3, 4), (0, 0)]  # [CLS] 이서연 ##과 [SEP]
    span = Span(0, 4, "PS", "이서연과")

    # '##과' 는 1글자 토큰이 아니라 '이서연' 토큰 안이 아님 → 마지막 문자를
    # 담은 토큰이 (3, 4), 길이 1이므로 신뢰하고 그대로 둔다.
    assert _arbitrate_one(text, offsets, span) == Span(0, 4, "PS", "이서연과")


# ── 자르면 안 되는 경우 ─────────────────────────────────────────────────


def test_길이_1_토큰은_조사_모양이어도_그대로_둔다() -> None:
    """'은'이 독립 토큰이면 모델이 글자 단위로 판단할 수 있었다는 뜻이다."""
    text = "송하은"
    offsets = [(0, 0), (0, 2), (2, 3), (0, 0)]  # [CLS] 송하 ##은 [SEP]
    span = Span(0, 3, "PS", "송하은")

    assert _arbitrate_one(text, offsets, span) == span


def test_받침_없는_음절_뒤_은은_조사가_아니다() -> None:
    """'지은' — '지'에 받침이 없으니 '은'은 주격조사일 수 없다. 이름이다."""
    text = "지은"
    offsets = [(0, 0), (0, 2), (0, 0)]  # [CLS] 지은 [SEP]
    span = Span(0, 2, "PS", "지은")

    assert _arbitrate_one(text, offsets, span) == span


def test_가을은_을을_떼지_않는다() -> None:
    """'가'에 받침이 없어 목적격조사 '을'이 아니다. LC 이름 '가을'."""
    text = "가을"
    offsets = [(0, 0), (0, 2), (0, 0)]
    span = Span(0, 2, "LC", "가을")

    assert _arbitrate_one(text, offsets, span) == span


def test_조사를_떼면_span이_비는_경우_그대로_둔다() -> None:
    text = "은은"
    offsets = [(0, 0), (0, 2), (0, 0)]
    span = Span(1, 2, "PS", "은")

    assert _arbitrate_one(text, offsets, span) == span


def test_span_순서와_개수는_보존된다() -> None:
    text = "송하은은서울"
    offsets = [(0, 0), (0, 2), (2, 4), (4, 6), (0, 0)]
    spans = [Span(0, 4, "PS", "송하은은"), Span(4, 6, "LC", "서울")]

    assert arbitrate_josa(spans, offsets, text) == [
        Span(0, 3, "PS", "송하은"),
        Span(4, 6, "LC", "서울"),
    ]


def test_마지막_문자가_어느_토큰에도_없으면_그대로_둔다() -> None:
    """max_length로 잘려 예측 뒤쪽에 오프셋이 없는 경우."""
    text = "송하은은"
    offsets = [(0, 0), (0, 2), (0, 0)]  # ##은은 토큰이 잘려 없음
    span = Span(0, 4, "PS", "송하은은")

    assert _arbitrate_one(text, offsets, span) == span


# ── 헬퍼 단위 테스트 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ch,expected",
    [
        ("은", True),
        ("강", True),
        ("물", True),
        ("가", False),
        ("지", False),
        ("A", False),
        (" ", False),
    ],
)
def test_받침_판정(ch: str, expected: bool) -> None:
    assert _has_batchim(ch) is expected


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("은이", 1),  # 이 (은에 받침)
        ("은은", 1),
        ("연과", 1),
        ("수에게", 2),
        ("연에게서", 3),
        ("지은", 0),  # 은이지만 지에 받침 없음
        ("가을", 0),
        ("철수", 0),
        ("은", 0),  # 앞 음절이 토큰에 없어 받침 확인 불가 → 보류
    ],
)
def test_조사_접미_길이(surface: str, expected: int) -> None:
    assert _josa_suffix_len(surface) == expected
