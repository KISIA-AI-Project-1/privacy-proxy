"""KLUE-NER 1차 학습.

``klue/bert-base`` 는 MLM으로 사전학습된 인코더일 뿐 NER 헤드가 없다.
여기서 헤드를 새로 만들어 일반 도메인 NER 모델까지 끌어올린다.
P3에서 이 결과물에 이커머스 CS 데이터로 2차 파인튜닝을 얹는다.

그래서 하이퍼파라미터를 하드코딩하지 않고 전부 인자로 받는다. P3에서 탐색
도구를 붙일 때 이 함수를 그대로 호출하면 된다.

    uv run python -m l4.ner.train_klue_ner --run-name klue-ner-base-e3
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

from l4.ner.data import build_datasets, restore_text
from l4.ner.labels import load_label_set
from l4.ner.metrics import NerEvaluator

BASE_MODEL = "klue/bert-base"
DATASET_PATH = "klue/klue"
DATASET_CONFIG = "ner"
OUTPUT_ROOT = Path("outputs")

# KLUE-NER은 test split을 제공하지 않는다. 검증 기준은 validation이다.
EVAL_SPLIT = "validation"


@dataclass
class TrainConfig:
    """P3에서 탐색 대상이 되는 값들."""

    run_name: str
    lr: float = 5e-5
    batch_size: int = 16
    epochs: int = 3
    max_length: int = 512
    seed: int = 42
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_train_samples: int | None = None
    latency_samples: int = 200
    extra: dict[str, Any] = field(default_factory=dict)


def _prepare_evaluator(raw_eval: Any, tokenized_eval: Any, label_set: Any) -> NerEvaluator:
    """평가에 필요한 원문·오프셋·정답을 미리 모아둔다.

    Trainer의 ``compute_metrics`` 는 예측 배열만 받으므로 문자 좌표를 되찾을
    수단이 없다. 평가 로더는 순서를 섞지 않으므로 인덱스가 그대로 대응한다.
    """
    texts = [restore_text(example["tokens"]) for example in raw_eval]
    gold = [example["ner_tags"] for example in raw_eval]
    offsets = tokenized_eval["offset_mapping"]
    return NerEvaluator(label_set, offsets, texts, gold)


def measure_latency(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    max_length: int,
    warmup: int = 10,
) -> dict[str, float]:
    """요청 1건당 추론 시간을 잰다.

    L4는 모든 프록시 요청에 걸리므로 지연시간이 곧 비용이다. 배치가 아니라
    batch_size=1로 재는 이유는, 실제 서비스에서는 요청이 하나씩 들어오기
    때문이다. 배치 처리량으로 재면 실제보다 낙관적으로 나온다.
    """
    model.eval()
    device = next(model.parameters()).device
    on_cuda = device.type == "cuda"
    durations: list[float] = []

    with torch.inference_mode():
        for index, text in enumerate(texts):
            encoded = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=max_length,
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}

            # CUDA 커널은 비동기로 큐에 쌓인다. 동기화 없이 재면 실제 연산이 아니라
            # 커널을 던져 넣는 시간만 재게 되어 말이 안 되게 빠른 값이 나온다.
            if on_cuda:
                torch.cuda.synchronize()
            started = time.perf_counter()
            model(**encoded)
            if on_cuda:
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - started

            if index >= warmup:  # 초기 몇 건은 워밍업이라 버린다
                durations.append(elapsed)

    if not durations:
        return {}
    array = np.array(durations)
    return {
        "latency_mean_s": float(array.mean()),
        "latency_p50_s": float(np.percentile(array, 50)),
        "latency_p95_s": float(np.percentile(array, 95)),
        "latency_samples": float(len(array)),
    }


def build_training_arguments(
    run_dir: Path,
    run_name: str,
    lr: float,
    batch_size: int,
    epochs: int,
    seed: int,
    weight_decay: float,
    warmup_ratio: float,
    steps_per_epoch: int,
) -> TrainingArguments:
    """transformers 버전 차이를 흡수해 TrainingArguments를 만든다.

    캐글·코랩 이미지의 transformers 버전이 로컬과 다르다. 인자 이름이 버전마다
    바뀌어서(``evaluation_strategy`` → ``eval_strategy``, ``warmup_ratio`` 제거)
    한쪽에 맞춰 하드코딩하면 다른 쪽에서 TypeError로 죽는다. 시그니처를 보고
    있는 인자만 넘긴다.
    """
    available = inspect.signature(TrainingArguments.__init__).parameters

    options: dict[str, Any] = {
        "output_dir": str(run_dir / "checkpoints"),
        "run_name": run_name,
        "learning_rate": lr,
        "per_device_train_batch_size": batch_size,
        "per_device_eval_batch_size": batch_size,
        "num_train_epochs": epochs,
        "weight_decay": weight_decay,
        "logging_strategy": "epoch",
        "save_strategy": "no",  # 체크포인트가 400MB+라 최종본만 따로 저장한다
        "seed": seed,
        "report_to": [],  # wandb 등 외부 도구 붙이지 않는다
        "dataloader_num_workers": 0,
    }

    # log_history에 epoch별 지표가 쌓이게 한다
    if "eval_strategy" in available:
        options["eval_strategy"] = "epoch"
    else:
        options["evaluation_strategy"] = "epoch"

    if "warmup_ratio" in available:
        options["warmup_ratio"] = warmup_ratio
    else:
        options["warmup_steps"] = int(steps_per_epoch * epochs * warmup_ratio)

    # GPU에서는 fp16이 2배 이상 빠르다. CPU에서는 켜면 오히려 느리거나 죽는다.
    if torch.cuda.is_available() and "fp16" in available:
        options["fp16"] = True

    return TrainingArguments(**options)


def train(
    run_name: str,
    lr: float = 5e-5,
    batch_size: int = 16,
    epochs: int = 3,
    max_length: int = 512,
    seed: int = 42,
    max_train_samples: int | None = None,
    latency_samples: int = 200,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """학습하고 metrics dict를 반환한다.

    Returns:
        ``eval`` (최종 검증 지표), ``latency``, ``log_history`` (epoch별 지표),
        ``config``, ``runtime_s`` 를 담은 dict.
    """
    config = TrainConfig(
        run_name=run_name,
        lr=lr,
        batch_size=batch_size,
        epochs=epochs,
        max_length=max_length,
        seed=seed,
        max_train_samples=max_train_samples,
        latency_samples=latency_samples,
    )
    run_dir = output_root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(DATASET_PATH, DATASET_CONFIG)
    label_set = load_label_set(dataset)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    # id2label/label2id를 넘기지 않으면 LABEL_0~LABEL_12로 잡혀서 저장된 모델의
    # 추론 결과를 사람이 읽을 수 없게 된다.
    model = AutoModelForTokenClassification.from_pretrained(
        BASE_MODEL,
        num_labels=label_set.num_labels,
        id2label=label_set.id2label,
        label2id=label_set.label2id,
    )

    tokenized = build_datasets(dataset, tokenizer, max_length)
    train_split = tokenized["train"]
    if max_train_samples is not None:
        train_split = train_split.select(range(min(max_train_samples, len(train_split))))

    evaluator = _prepare_evaluator(dataset[EVAL_SPLIT], tokenized[EVAL_SPLIT], label_set)

    steps_per_epoch = math.ceil(len(train_split) / batch_size)
    arguments = build_training_arguments(
        run_dir=run_dir,
        run_name=run_name,
        lr=lr,
        batch_size=batch_size,
        epochs=epochs,
        seed=seed,
        weight_decay=config.weight_decay,
        warmup_ratio=config.warmup_ratio,
        steps_per_epoch=steps_per_epoch,
    )

    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=train_split.remove_columns(["offset_mapping", "char_length"]),
        eval_dataset=tokenized[EVAL_SPLIT].remove_columns(["offset_mapping", "char_length"]),
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=evaluator,
    )

    started = time.perf_counter()
    trainer.train()
    runtime = time.perf_counter() - started

    eval_metrics = trainer.evaluate()

    model_dir = run_dir / "model"
    trainer.save_model(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))

    latency = measure_latency(
        model,
        tokenizer,
        [restore_text(e["tokens"]) for e in dataset[EVAL_SPLIT].select(range(latency_samples))],
        max_length,
    )

    result: dict[str, Any] = {
        "run_name": run_name,
        "config": vars(config),
        "eval": {k: v for k, v in eval_metrics.items() if isinstance(v, int | float)},
        "latency": latency,
        "log_history": trainer.state.log_history,
        "runtime_s": runtime,
        "model_dir": str(model_dir),
    }
    (run_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KLUE-NER 1차 학습")
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-train-samples",
        type=int,
        default=None,
        help="스모크 테스트용. 학습 데이터를 이 개수로 자른다.",
    )
    parser.add_argument("--latency-samples", type=int, default=200)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = train(
        run_name=args.run_name,
        lr=args.lr,
        batch_size=args.batch_size,
        epochs=int(args.epochs) if float(args.epochs).is_integer() else args.epochs,
        max_length=args.max_length,
        seed=args.seed,
        max_train_samples=args.max_train_samples,
        latency_samples=args.latency_samples,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {"eval": result["eval"], "latency": result["latency"]}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
