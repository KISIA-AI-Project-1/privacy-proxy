"""서브워드 → 문자 좌표 복원 테스트.

여기가 틀리면 학습 라벨과 평가 지표가 동시에 어긋난다. 실제로 공백 잇기가
없을 때 평가 상한이 0.98에서 0.73으로 떨어지는 것을 확인했다.
"""

from l4.ner.data import expand_subword_to_char, restore_text
from l4.ner.labels import LabelSet

LABELS = LabelSet(
    (
        "B-DT",
        "I-DT",
        "B-LC",
        "I-LC",
        "B-OG",
        "I-OG",
        "B-PS",
        "I-PS",
        "B-QT",
        "I-QT",
        "B-TI",
        "I-TI",
        "O",
    )
)
B_PS, I_PS = 6, 7
B_LC, I_LC = 2, 3
OUT = 12


def test_원문_복원은_단순_결합() -> None:
    assert restore_text(["안", "녕", " ", "하", "세", "요"]) == "안녕 하세요"


def test_서브워드_내부는_첫_글자만_B가_된다() -> None:
    """'김철수' 한 토큰이 B-PS로 예측되면 나머지 두 글자는 I-PS여야 한다.

    전부 B-PS로 두면 병합 시 한 글자짜리 엔티티 3개로 쪼개진다.
    """
    tags = expand_subword_to_char([(0, 0), (0, 3), (0, 0)], [OUT, B_PS, OUT], LABELS, 3)

    assert tags == ["B-PS", "I-PS", "I-PS"]


def test_특수토큰은_건너뛴다() -> None:
    tags = expand_subword_to_char([(0, 0), (0, 2), (0, 0)], [OUT, OUT, OUT], LABELS, 2)

    assert tags == ["O", "O"]


def test_엔티티_내부_공백을_잇는다() -> None:
    """'서울 강남구' — 토크나이저가 공백을 어느 토큰에도 넣지 않는다.

    KLUE-NER 정답은 이 공백에 I-LC를 붙인다. 구멍을 O로 두면 엔티티가
    '서울'과 '강남구' 둘로 갈라진다. 정답 엔티티의 약 14%가 여기 해당한다.
    """
    text = "서울 강남구"
    offsets = [(0, 0), (0, 2), (3, 6), (0, 0)]

    tags = expand_subword_to_char(offsets, [OUT, B_LC, I_LC, OUT], LABELS, len(text))

    assert tags == ["B-LC", "I-LC", "I-LC", "I-LC", "I-LC", "I-LC"]


def test_엔티티_사이_공백은_잇지_않는다() -> None:
    """뒤가 B-로 시작하면 다른 엔티티다. 이으면 두 사람이 한 명이 된다."""
    text = "김철수 이영희"
    offsets = [(0, 0), (0, 3), (4, 7), (0, 0)]

    tags = expand_subword_to_char(offsets, [OUT, B_PS, B_PS, OUT], LABELS, len(text))

    assert tags[3] == "O"
    assert tags == ["B-PS", "I-PS", "I-PS", "O", "B-PS", "I-PS", "I-PS"]


def test_타입이_다르면_공백을_잇지_않는다() -> None:
    text = "김철수 서울"
    offsets = [(0, 0), (0, 3), (4, 6), (0, 0)]

    tags = expand_subword_to_char(offsets, [OUT, B_PS, I_LC, OUT], LABELS, len(text))

    assert tags[3] == "O"


def test_O_뒤의_공백은_잇지_않는다() -> None:
    text = "안녕 서울"
    offsets = [(0, 0), (0, 2), (3, 5), (0, 0)]

    tags = expand_subword_to_char(offsets, [OUT, OUT, B_LC, OUT], LABELS, len(text))

    assert tags == ["O", "O", "O", "B-LC", "I-LC"]


def test_잘린_뒤쪽은_O로_남는다() -> None:
    """max_length로 잘리면 뒤쪽 문자는 예측이 없다. 누락으로 정직하게 잡힌다."""
    tags = expand_subword_to_char([(0, 0), (0, 2)], [OUT, B_PS], LABELS, 5)

    assert tags == ["B-PS", "I-PS", "O", "O", "O"]


def test_오프셋이_원문_길이를_넘으면_잘라낸다() -> None:
    tags = expand_subword_to_char([(0, 10)], [B_PS], LABELS, 3)

    assert tags == ["B-PS", "I-PS", "I-PS"]
