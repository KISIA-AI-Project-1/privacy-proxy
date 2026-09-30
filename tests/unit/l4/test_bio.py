"""BIO span 병합 테스트.

이 모듈은 학습 평가와 런타임 추론 양쪽에서 쓰이므로, 여기가 깨지면 지표와
실제 탐지가 동시에 틀어진다. 픽스처는 전부 가상값이다.
"""

import pytest
from l4.ner.bio import Span, merge_bio_spans, spans_to_bio


def test_정상_bio_시퀀스() -> None:
    text = "김철수님께"
    labels = ["B-PS", "I-PS", "I-PS", "O", "O"]

    assert merge_bio_spans(labels, text) == [Span(0, 3, "PS", "김철수")]


def test_전부_O이면_span_없음() -> None:
    assert merge_bio_spans(["O"] * 4, "안녕하세") == []


def test_불량_I로_시작하면_B로_승격한다() -> None:
    """recall 우선 정책. 무시하면 인명이 통째로 새어나간다."""
    text = "김철수님"
    labels = ["I-PS", "I-PS", "I-PS", "O"]

    assert merge_bio_spans(labels, text) == [Span(0, 3, "PS", "김철수")]


def test_O_다음의_I도_새_엔티티로_연다() -> None:
    text = "가김철수"
    labels = ["O", "I-PS", "I-PS", "I-PS"]

    assert merge_bio_spans(labels, text) == [Span(1, 4, "PS", "김철수")]


def test_타입_전환은_경계가_된다() -> None:
    """I-PS 뒤의 I-LC는 이어붙이지 않고 끊는다."""
    text = "김철수서울시"
    labels = ["B-PS", "I-PS", "I-PS", "I-LC", "I-LC", "I-LC"]

    assert merge_bio_spans(labels, text) == [
        Span(0, 3, "PS", "김철수"),
        Span(3, 6, "LC", "서울시"),
    ]


def test_연속된_B는_별개_엔티티다() -> None:
    """'김철수 이영희'처럼 같은 타입이 붙어 있어도 B-가 새로 오면 끊는다."""
    text = "김철수이영희"
    labels = ["B-PS", "I-PS", "I-PS", "B-PS", "I-PS", "I-PS"]

    assert merge_bio_spans(labels, text) == [
        Span(0, 3, "PS", "김철수"),
        Span(3, 6, "PS", "이영희"),
    ]


def test_문장_끝에서_열린_span도_닫힌다() -> None:
    text = "고객김철수"
    labels = ["O", "O", "B-PS", "I-PS", "I-PS"]

    assert merge_bio_spans(labels, text) == [Span(2, 5, "PS", "김철수")]


def test_한_글자_엔티티() -> None:
    assert merge_bio_spans(["O", "B-PS", "O"], "가나다") == [Span(1, 2, "PS", "나")]


def test_여러_엔티티가_O로_구분된다() -> None:
    text = "김철수는서울에"
    labels = ["B-PS", "I-PS", "I-PS", "O", "B-LC", "I-LC", "O"]

    assert merge_bio_spans(labels, text) == [
        Span(0, 3, "PS", "김철수"),
        Span(4, 6, "LC", "서울"),
    ]


def test_길이가_어긋나면_에러() -> None:
    with pytest.raises(ValueError, match="라벨"):
        merge_bio_spans(["O", "O"], "세글자")


def test_형식이_아닌_라벨은_에러() -> None:
    with pytest.raises(ValueError, match="BIO 라벨 형식"):
        merge_bio_spans(["B-PS", "PS", "O"], "김철수")


@pytest.mark.parametrize("bad", ["B-", "X-PS", "-PS"])
def test_깨진_라벨_형식들(bad: str) -> None:
    with pytest.raises(ValueError):
        merge_bio_spans([bad], "김")


# ── spans_to_bio: 평가 경로에서 seqeval에 넘기기 직전에 쓴다 ──────────────


def test_span에서_bio로_되돌린다() -> None:
    spans = [Span(0, 3, "PS", "김철수"), Span(4, 6, "LC", "서울")]

    assert spans_to_bio(spans, 7) == [
        "B-PS",
        "I-PS",
        "I-PS",
        "O",
        "B-LC",
        "I-LC",
        "O",
    ]


def test_span_없으면_전부_O() -> None:
    assert spans_to_bio([], 3) == ["O", "O", "O"]


@pytest.mark.parametrize(
    "labels,text",
    [
        (["B-PS", "I-PS", "O", "B-LC"], "김철수서"),
        (["I-PS", "I-PS", "I-LC", "O"], "김철수님"),  # 불량 입력도 왕복 가능해야
        (["O", "O", "O", "O"], "가나다라"),
    ],
)
def test_병합_후_되돌리면_정규형이_된다(labels: list[str], text: str) -> None:
    """merge → spans_to_bio 는 멱등이어야 한다.

    평가에서 예측·정답을 모두 이 경로로 통과시키므로, 여기가 안정적이지 않으면
    지표가 흔들린다.
    """
    spans = merge_bio_spans(labels, text)
    canonical = spans_to_bio(spans, len(text))

    assert merge_bio_spans(canonical, text) == spans


def test_범위를_벗어난_span은_에러() -> None:
    with pytest.raises(ValueError, match="범위"):
        spans_to_bio([Span(0, 5, "PS", "김철수")], 3)


def test_겹치는_span은_에러() -> None:
    with pytest.raises(ValueError, match="겹친다"):
        spans_to_bio([Span(0, 3, "PS", "김철수"), Span(2, 4, "LC", "수님")], 5)


def test_빈_span은_만들_수_없다() -> None:
    with pytest.raises(ValueError, match="빈 span"):
        Span(2, 2, "PS", "")
