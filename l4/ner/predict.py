"""학습된 모델로 원문에서 엔티티 span을 뽑는다 — 런타임 추론 경로.

학습 평가와 **완전히 같은** 함수들을 쓴다(``expand_subword_to_char`` →
``merge_bio_spans``). 두 경로가 갈라지면 "평가에서는 잡혔는데 서비스에서는
놓치는" 차이가 생기고, L4에서 그건 곧 개인정보 유출이다.

다음 주 ``alignment/`` (조사 경계 중재)가 이 함수의 출력을 입력으로 받는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

from l4.ner.bio import Span, merge_bio_spans
from l4.ner.data import expand_subword_to_char
from l4.ner.labels import LabelSet


def load_model(model_dir: str | Path) -> tuple[Any, Any, LabelSet]:
    """저장된 run의 모델·토크나이저·라벨 집합을 불러온다.

    라벨 이름은 모델 config의 ``id2label`` 에서 읽는다. 학습 시
    ``id2label`` 을 넘겨줬기 때문에 여기서 데이터셋을 다시 받을 필요가 없다.
    """
    model = AutoModelForTokenClassification.from_pretrained(str(model_dir))
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    id2label: dict[int, str] = model.config.id2label
    names = tuple(id2label[index] for index in sorted(id2label))
    return model, tokenizer, LabelSet(names)


def predict_spans(
    text: str,
    model: Any,
    tokenizer: Any,
    label_set: LabelSet,
    max_length: int = 512,
) -> list[Span]:
    """평문 하나에서 엔티티 span 리스트를 뽑는다."""
    encoded = tokenizer(
        text,
        return_offsets_mapping=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    offsets = encoded.pop("offset_mapping")[0].tolist()

    model.eval()
    with torch.inference_mode():
        logits = model(**encoded).logits

    predicted_ids = logits.argmax(dim=-1)[0].tolist()
    char_tags = expand_subword_to_char(offsets, predicted_ids, label_set, len(text))
    return merge_bio_spans(char_tags, text)
