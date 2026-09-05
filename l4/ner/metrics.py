"""seqeval 엔티티 F1 기반 평가.

주 지표는 **엔티티 F1**이지 문자 F1이 아니다. 파이프라인이 span 단위로
동작하기 때문이다. '김철수'를 '김철'로 잡으면 문자 F1은 0.67을 주지만
실제로는 '수'가 원문에 남아 외부 LLM으로 나간다. 부분 점수를 주면 안 된다.

평가 경로:
    서브워드 예측 → 문자 단위로 펼치기 → bio.merge_bio_spans → 정규 BIO
    → seqeval

예측과 정답을 모두 ``merge_bio_spans`` 로 통과시킨다. 지표가 재는 경계와
런타임이 실제로 뽑는 경계가 정의상 같아진다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from seqeval.metrics import classification_report

from l4.ner.bio import merge_bio_spans, spans_to_bio
from l4.ner.data import expand_subword_to_char
from l4.ner.labels import L4_ENTITY_TYPES, PRIMARY_ENTITY_TYPE, LabelSet


def canonicalize(
    offsets: Sequence[Sequence[int]],
    label_ids: Sequence[int],
    label_set: LabelSet,
    char_length: int,
    text: str,
) -> list[str]:
    """서브워드 라벨 → 문자 BIO → span 병합 → 정규 BIO."""
    char_tags = expand_subword_to_char(offsets, label_ids, label_set, char_length)
    spans = merge_bio_spans(char_tags, text)
    return spans_to_bio(spans, char_length)


def canonicalize_gold(
    char_tag_ids: Sequence[int],
    label_set: LabelSet,
    text: str,
) -> list[str]:
    """정답도 같은 병합기를 통과시킨다.

    정답은 이미 문자 단위라 펼치기가 필요 없지만, 병합 규칙(불량 I- 승격 등)을
    예측과 똑같이 적용해야 지표가 한쪽으로 기울지 않는다.
    """
    tags = label_set.to_bio(list(char_tag_ids))
    spans = merge_bio_spans(tags, text)
    return spans_to_bio(spans, len(text))


def score(
    gold_sequences: Sequence[Sequence[str]],
    predicted_sequences: Sequence[Sequence[str]],
) -> dict[str, float]:
    """seqeval 리포트를 평평한 지표 dict로 변환한다.

    포함 내용:
      - ``f1`` / ``precision`` / ``recall``  전체 (micro). 외부 비교용 주 지표
      - ``{TAG}_f1`` 등 태그별 지표
      - ``ps_recall``  인명 누락률. 실무 판단 지표
      - ``l4_f1``  L4가 실제로 쓰는 태그(PS·LC)만의 micro F1
    """
    report: dict[str, Any] = classification_report(
        list(gold_sequences),
        list(predicted_sequences),
        output_dict=True,
        zero_division=0,
    )

    metrics: dict[str, float] = {}
    overall = report.get("micro avg") or report.get("weighted avg") or {}
    metrics["f1"] = float(overall.get("f1-score", 0.0))
    metrics["precision"] = float(overall.get("precision", 0.0))
    metrics["recall"] = float(overall.get("recall", 0.0))

    for tag, values in report.items():
        if tag.endswith("avg") or not isinstance(values, dict):
            continue
        metrics[f"{tag}_precision"] = float(values["precision"])
        metrics[f"{tag}_recall"] = float(values["recall"])
        metrics[f"{tag}_f1"] = float(values["f1-score"])
        metrics[f"{tag}_support"] = float(values["support"])

    # 전체 F1만 보면 안 된다. OG/DT/TI/QT는 L4가 쓰지 않는다.
    metrics["ps_recall"] = metrics.get(f"{PRIMARY_ENTITY_TYPE}_recall", 0.0)
    metrics["l4_f1"] = _micro_f1_for(report, L4_ENTITY_TYPES)
    metrics["l4_recall"] = _micro_recall_for(report, L4_ENTITY_TYPES)
    return metrics


def _micro_f1_for(report: dict[str, Any], tags: Sequence[str]) -> float:
    precision = _weighted(report, tags, "precision")
    recall = _weighted(report, tags, "recall")
    if precision + recall == 0.0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _micro_recall_for(report: dict[str, Any], tags: Sequence[str]) -> float:
    return _weighted(report, tags, "recall")


def _weighted(report: dict[str, Any], tags: Sequence[str], key: str) -> float:
    total = sum(float(report[t]["support"]) for t in tags if t in report)
    if total == 0.0:
        return 0.0
    return (
        sum(float(report[t][key]) * float(report[t]["support"]) for t in tags if t in report)
        / total
    )


class NerEvaluator:
    """Trainer의 ``compute_metrics`` 로 넘기는 콜러블.

    Trainer는 예측 배열만 넘겨주므로, 문자 좌표 복원에 필요한 오프셋과 원문은
    생성 시점에 미리 들고 있는다. 평가 로더는 순서를 섞지 않으므로 인덱스가
    그대로 대응한다.
    """

    def __init__(
        self,
        label_set: LabelSet,
        offsets: Sequence[Sequence[Sequence[int]]],
        texts: Sequence[str],
        gold_char_tags: Sequence[Sequence[int]],
    ) -> None:
        if not (len(offsets) == len(texts) == len(gold_char_tags)):
            raise ValueError("offsets/texts/gold 길이가 어긋난다")
        self.label_set = label_set
        self.offsets = offsets
        self.texts = texts
        self.gold_char_tags = gold_char_tags

    def __call__(self, eval_prediction: Any) -> dict[str, float]:
        logits = eval_prediction.predictions
        if isinstance(logits, tuple):
            logits = logits[0]
        predicted_ids = np.argmax(logits, axis=-1)

        gold_sequences: list[list[str]] = []
        predicted_sequences: list[list[str]] = []

        for index, text in enumerate(self.texts):
            offsets = self.offsets[index]
            token_count = len(offsets)
            predicted_sequences.append(
                canonicalize(
                    offsets,
                    predicted_ids[index][:token_count].tolist(),
                    self.label_set,
                    len(text),
                    text,
                )
            )
            gold_sequences.append(
                canonicalize_gold(self.gold_char_tags[index], self.label_set, text)
            )

        return score(gold_sequences, predicted_sequences)
