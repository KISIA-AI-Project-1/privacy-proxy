"""KLUE-NER 전처리.

핵심 원칙: 학습과 런타임 추론이 **같은 경로**를 쓴다.

런타임에서 L4가 받는 것은 사용자가 보낸 평문이다. 따라서 학습에서도 평문을
그대로 토크나이징하고 ``offset_mapping`` 으로 좌표를 되찾는다.
(``is_split_into_words=True`` 를 쓰면 학습만 미리 쪼개진 입력을 보게 되어
학습-추론 불일치가 생긴다.)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from l4.ner.bio import OUTSIDE
from l4.ner.labels import LabelSet

# Trainer에 넘기기 전에 떼어내야 하는 컬럼. 모델 forward 인자가 아니다.
NON_MODEL_COLUMNS = ("offset_mapping", "char_length")

IGNORE_INDEX = -100


def restore_text(tokens: Sequence[str]) -> str:
    """문자 단위 토큰을 원문으로 되돌린다.

    ``sentence`` 필드는 ``<영동고속도로:LC>`` 형태의 인라인 마크업이 들어 있어
    원문이 아니다. 절대 쓰지 않는다.
    """
    return "".join(tokens)


def encode_example(
    example: dict[str, Any],
    tokenizer: Any,
    max_length: int,
) -> dict[str, Any]:
    """한 문장을 모델 입력과 서브워드 라벨로 변환한다.

    ``ner_tags`` 는 문자 인덱스와 1:1이므로 그대로 원문 좌표계다. 서브워드의
    라벨은 그 서브워드가 시작하는 문자의 라벨을 쓴다.
    """
    text = restore_text(example["tokens"])
    char_tags: list[int] = example["ner_tags"]

    encoded = tokenizer(
        text,
        return_offsets_mapping=True,
        truncation=True,
        max_length=max_length,
    )

    labels: list[int] = []
    for start, end in encoded["offset_mapping"]:
        if start == end:  # [CLS], [SEP], 패딩
            labels.append(IGNORE_INDEX)
        else:
            labels.append(char_tags[start])

    encoded["labels"] = labels
    # 평가에서 서브워드 예측을 문자 좌표로 되펼치는 데 필요하다.
    encoded["char_length"] = len(text)
    return dict(encoded)


def expand_subword_to_char(
    offsets: Sequence[Sequence[int]],
    label_ids: Sequence[int],
    label_set: LabelSet,
    char_length: int,
) -> list[str]:
    """서브워드 단위 예측을 문자 단위 BIO 시퀀스로 펼친다.

    두 가지를 처리한다.

    1. **서브워드 내부의 BIO 정규화.** ``B-PS`` 로 예측된 서브워드가 3글자를
       덮으면 첫 글자만 ``B-PS`` 이고 나머지는 ``I-PS`` 여야 한다. 전부
       ``B-PS`` 로 두면 병합 시 3개의 엔티티로 쪼개진다.

    2. **엔티티 내부 공백 잇기.** 토크나이저의 ``offset_mapping`` 은 공백을
       어느 토큰에도 넣지 않아 문자 좌표에 구멍이 생긴다. 그런데 KLUE-NER
       정답에서 전체 엔티티의 약 14%가 공백을 품고 있고(예: '서울 강남구'),
       그 공백에는 ``I-LC`` 가 붙어 있다. 구멍을 ``O`` 로 두면 이 엔티티들이
       전부 두 조각으로 갈라져 엔티티 F1이 실제보다 크게 낮게 나온다.
       앞뒤가 같은 타입으로 이어질 때만 ``I-`` 로 메운다.

    Args:
        offsets: 토큰별 ``(start, end)`` 문자 오프셋.
        label_ids: 토큰별 예측 라벨 인덱스. ``offsets`` 와 길이가 같아야 한다.
        label_set: 라벨 인덱스 → 이름 매핑.
        char_length: 원문 길이. 잘린 뒤쪽은 ``O`` 로 남는다.
    """
    if len(offsets) != len(label_ids):
        raise ValueError(f"오프셋 {len(offsets)}개 ≠ 라벨 {len(label_ids)}개")

    tags = [OUTSIDE] * char_length
    covered = [False] * char_length

    for (start, end), label_id in zip(offsets, label_ids, strict=True):
        if start == end:  # 특수 토큰
            continue
        end = min(end, char_length)
        if start >= end:
            continue

        name = label_set.names[label_id]
        for offset, position in enumerate(range(start, end)):
            covered[position] = True
            if name == OUTSIDE:
                tags[position] = OUTSIDE
            elif offset == 0:
                tags[position] = name
            else:
                # 서브워드 두 번째 글자부터는 항상 I-
                tags[position] = "I-" + name.split("-", 1)[1]

    _bridge_gaps(tags, covered)
    return tags


def _bridge_gaps(tags: list[str], covered: list[bool]) -> None:
    """토큰에 안 잡힌 문자(주로 공백)를 앞뒤가 같은 엔티티일 때만 이어준다."""
    length = len(tags)
    index = 0
    while index < length:
        if covered[index]:
            index += 1
            continue

        gap_end = index
        while gap_end < length and not covered[gap_end]:
            gap_end += 1

        previous = tags[index - 1] if index > 0 else OUTSIDE
        following = tags[gap_end] if gap_end < length else OUTSIDE

        if previous != OUTSIDE and following.startswith("I-"):
            previous_type = previous.split("-", 1)[1]
            if previous_type == following.split("-", 1)[1]:
                for position in range(index, gap_end):
                    tags[position] = "I-" + previous_type

        index = gap_end


def build_datasets(
    dataset: Any,
    tokenizer: Any,
    max_length: int,
) -> Any:
    """train/validation 전체를 인코딩한다. 원본 컬럼은 떨군다."""
    return dataset.map(
        lambda example: encode_example(example, tokenizer, max_length),
        remove_columns=dataset["train"].column_names,
        desc="tokenizing",
    )
