"""alignment.py 적용 전/후 지표 비교 — 재학습 없이 기존 체크포인트로 평가.

``klue-ner-base-e3``는 이미 학습이 끝났다. validation을 한 번만 예측하고,
그 로짓을 ``NerEvaluator``에 ``apply_josa=False``/``True``로 각각 통과시켜
지표 두 벌을 뽑는다. 학습을 다시 돌릴 필요가 없다.

    uv run python -m l4.ner.evaluate_alignment --model-dir outputs/klue-ner-base-e3/model

Colab에서는 노트북 8-1번 셀이 이 함수를 그대로 호출한다.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from datasets import load_dataset
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

from l4.ner.data import build_datasets, restore_text
from l4.ner.labels import LabelSet
from l4.ner.metrics import NerEvaluator
from l4.ner.train_klue_ner import DATASET_CONFIG, DATASET_PATH, EVAL_SPLIT

# docs/experiments/klue-ner-1st/RESULTS.md 기준. 평가 경로 자체의 한계
# (조사 경계) 때문에 F1 1.0이 아니라 이 값이 상한이다.
CEILING_F1 = 0.9814


def run(model_dir: Path, max_length: int = 512, batch_size: int = 16) -> dict[str, Any]:
    """validation 전체에 대해 적용 전/후 지표를 계산한다."""
    model = AutoModelForTokenClassification.from_pretrained(str(model_dir))
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    id2label: dict[int, str] = model.config.id2label
    label_set = LabelSet(tuple(id2label[index] for index in sorted(id2label)))

    dataset = load_dataset(DATASET_PATH, DATASET_CONFIG)
    tokenized = build_datasets(dataset, tokenizer, max_length)
    raw_eval = dataset[EVAL_SPLIT]
    texts = [restore_text(example["tokens"]) for example in raw_eval]
    gold = [example["ner_tags"] for example in raw_eval]
    offsets = tokenized[EVAL_SPLIT]["offset_mapping"]

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=tempfile.mkdtemp(prefix="evaluate_alignment_"),
            per_device_eval_batch_size=batch_size,
            report_to=[],
        ),
        data_collator=DataCollatorForTokenClassification(tokenizer),
    )
    eval_dataset = tokenized[EVAL_SPLIT].remove_columns(["offset_mapping", "char_length"])
    predictions = trainer.predict(eval_dataset)  # 로짓은 한 번만 뽑는다

    before = NerEvaluator(label_set, offsets, texts, gold, apply_josa=False)(predictions)
    after = NerEvaluator(label_set, offsets, texts, gold, apply_josa=True)(predictions)

    print(f"{'지표':<12}{'적용 전':>10}{'적용 후':>10}{'상한 대비(후)':>14}")
    for key in ("f1", "ps_recall", "l4_f1", "l4_recall"):
        b, a = before.get(key, 0.0), after.get(key, 0.0)
        print(f"{key:<12}{b:>10.4f}{a:>10.4f}{a / CEILING_F1:>14.4f}")

    return {"before": before, "after": after, "ceiling_f1": CEILING_F1}


def main() -> None:
    parser = argparse.ArgumentParser(description="alignment.py 적용 전/후 비교")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--output", type=Path, default=None, help="결과 json 저장 경로")
    args = parser.parse_args()

    result = run(args.model_dir, args.max_length)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {args.output}")


if __name__ == "__main__":
    main()
