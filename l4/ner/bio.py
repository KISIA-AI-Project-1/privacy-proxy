"""BIO 라벨 시퀀스 ↔ 엔티티 span 변환.

학습 평가(metrics.py)와 런타임 추론 양쪽에서 같은 함수를 쓴다. 두 경로가
서로 다른 병합 규칙을 쓰면 "평가에서는 잡혔는데 서비스에서는 안 잡히는"
차이가 생기고, L4에서 그 차이는 곧 개인정보 유출이다.

torch/transformers를 import하지 않는다. 런타임 추론 경로가 가벼워야 하고,
이 로직만 따로 테스트할 수 있어야 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

OUTSIDE = "O"


@dataclass(frozen=True)
class Span:
    """원문 문자열에 대한 반열린 구간 [start, end) 의 엔티티."""

    start: int
    end: int
    entity_type: str
    text: str

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"빈 span: start={self.start} end={self.end}")


def _split_label(label: str) -> tuple[str, str]:
    """'B-PS' -> ('B', 'PS'). 'O' -> ('O', '')."""
    if label == OUTSIDE:
        return OUTSIDE, ""
    prefix, sep, entity_type = label.partition("-")
    if sep != "-" or prefix not in ("B", "I") or not entity_type:
        raise ValueError(f"BIO 라벨 형식이 아니다: {label!r}")
    return prefix, entity_type


def merge_bio_spans(labels: Sequence[str], text: str) -> list[Span]:
    """문자 단위 BIO 라벨을 엔티티 span으로 병합한다.

    병합 중단 조건: ``O`` 등장, 엔티티 타입 전환, 새 ``B-`` 등장.

    불량 시퀀스 정책 — ``B-`` 없이 등장한 ``I-`` 는 무시하지 않고 ``B-`` 로
    승격한다. L4는 recall 우선이다. 누락(FN)은 개인정보가 그대로 외부 LLM에
    나가는 것이지만, 오탐(FP)은 L5 위험도 평가와 L6 토큰화를 거치며 걸러진다.
    한쪽 비용이 압도적으로 크므로 애매하면 잡는 쪽을 택한다.

    Args:
        labels: 문자 하나당 라벨 하나. ``text`` 와 길이가 같아야 한다.
        text: 원문. span의 ``text`` 필드를 채우는 데 쓴다.

    Returns:
        원문 등장 순서대로 정렬된 span 리스트.

    Raises:
        ValueError: 길이가 어긋나거나 BIO 형식이 아닌 라벨이 있을 때.
    """
    if len(labels) != len(text):
        raise ValueError(f"라벨 {len(labels)}개 ≠ 원문 {len(text)}자")

    spans: list[Span] = []
    start: int | None = None
    current_type = ""

    def flush(end: int) -> None:
        nonlocal start, current_type
        if start is not None:
            spans.append(Span(start, end, current_type, text[start:end]))
        start = None
        current_type = ""

    for index, label in enumerate(labels):
        prefix, entity_type = _split_label(label)

        if prefix == OUTSIDE:
            flush(index)
        elif prefix == "B":
            flush(index)
            start, current_type = index, entity_type
        elif entity_type != current_type:
            # B- 없이 시작했거나 타입이 바뀐 I-. 둘 다 새 엔티티로 연다.
            flush(index)
            start, current_type = index, entity_type

    flush(len(labels))
    return spans


def spans_to_bio(spans: Sequence[Span], length: int) -> list[str]:
    """span 리스트를 정규 BIO 시퀀스로 되돌린다.

    평가에서 쓴다. 예측과 정답을 모두 ``merge_bio_spans`` 로 한 번 통과시킨 뒤
    이 함수로 다시 펼쳐서 seqeval에 넘기면, 지표가 재는 엔티티 경계와 런타임이
    실제로 뽑는 경계가 정의상 같아진다.

    Raises:
        ValueError: span이 ``length`` 밖으로 나가거나 서로 겹칠 때.
    """
    tags = [OUTSIDE] * length
    for span in spans:
        if span.start < 0 or span.end > length:
            raise ValueError(f"span {span} 이 길이 {length} 범위를 벗어난다")
        if any(tag != OUTSIDE for tag in tags[span.start : span.end]):
            raise ValueError(f"span {span} 이 앞선 span과 겹친다")
        tags[span.start] = f"B-{span.entity_type}"
        for index in range(span.start + 1, span.end):
            tags[index] = f"I-{span.entity_type}"
    return tags
