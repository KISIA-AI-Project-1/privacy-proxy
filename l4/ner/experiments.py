"""베이스라인 실험 러너.

목적은 성능 최적화가 아니라 **재현 가능한 베이스라인 확보**다. run을 늘리지
않는다. 4개면 충분하고, 그 이상은 P3에서 도메인 데이터를 붙인 뒤에 한다.

    uv run python -m l4.ner.experiments --only klue-ner-base-e3
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.ner.train_klue_ner import OUTPUT_ROOT, train


@dataclass(frozen=True)
class Experiment:
    run_name: str
    lr: float
    batch_size: int
    epochs: int
    max_length: int
    note: str


EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment("klue-ner-base-e3", 5e-5, 16, 3, 512, "기준선"),
    Experiment("klue-ner-base-e6", 5e-5, 16, 6, 512, "에폭을 늘리면 더 오르는가"),
    Experiment("klue-ner-lr3e5-e3", 3e-5, 16, 3, 512, "학습률을 낮추면 안정적인가"),
    # 성능 실험이 아니라 지연시간 실험이다. L4는 모든 요청에 걸리는 추론이라
    # 지연시간이 그대로 비용이 된다. F1과 추론 시간을 함께 본다.
    Experiment("klue-ner-len256-e3", 5e-5, 16, 3, 256, "길이를 줄이면 얼마나 빨라지는가"),
)

# 이 밑으로 떨어지면 설정 오류를 의심한다. 나머지 run을 돌리기 전에 점검한다.
MIN_ACCEPTABLE_F1 = 0.5


def write_log_history(run_name: str, history: list[dict[str, Any]], output_root: Path) -> Path:
    """epoch별 지표를 CSV로 남긴다. visualize.py가 이걸 읽는다."""
    path = output_root / run_name / "log_history.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    columns: list[str] = []
    for entry in history:
        for key in entry:
            if key not in columns:
                columns.append(key)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(history)
    return path


def write_summary(results: list[dict[str, Any]], output_root: Path) -> Path:
    """run 간 비교용 요약. F1과 지연시간을 한 표에 둔다."""
    path = output_root / "summary.csv"
    columns = [
        "run_name",
        "lr",
        "batch_size",
        "epochs",
        "max_length",
        "f1",
        "precision",
        "recall",
        "PS_f1",
        "PS_recall",
        "LC_f1",
        "l4_f1",
        "l4_recall",
        "latency_p50_s",
        "latency_p95_s",
        "runtime_s",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            row: dict[str, Any] = {"run_name": result["run_name"]}
            row.update({k: v for k, v in result["config"].items() if k in columns})
            row.update({k.removeprefix("eval_"): v for k, v in result["eval"].items()})
            row.update(result.get("latency", {}))
            row["runtime_s"] = round(float(result.get("runtime_s", 0.0)), 1)
            writer.writerow(row)
    return path


def run(
    experiments: tuple[Experiment, ...] = EXPERIMENTS,
    output_root: Path = OUTPUT_ROOT,
    stop_on_low_f1: bool = True,
    save_steps: int = 0,
    save_total_limit: int = 1,
    skip_completed: bool = True,
) -> list[dict[str, Any]]:
    """실험을 순서대로 돌린다.

    첫 run의 F1이 임계값 미만이면 멈춘다. 설정이 틀린 채로 나머지 run을 돌리면
    몇 시간을 버린다.

    코랩은 세션이 끊길 수 있다. 두 단계로 대비한다.
      - run 단위: 이미 metrics.json이 있는 run은 건너뛴다(``skip_completed``)
      - 스텝 단위: ``save_steps`` > 0 이면 중간 체크포인트에서 이어서 돌린다
    끊긴 뒤 셀을 다시 실행하면 끝난 run은 넘기고 하던 데서 이어간다.
    """
    results: list[dict[str, Any]] = []

    for index, experiment in enumerate(experiments):
        print(
            f"\n=== [{index + 1}/{len(experiments)}] {experiment.run_name} ({experiment.note}) ===",
            flush=True,
        )
        finished = output_root / experiment.run_name / "metrics.json"
        if skip_completed and finished.exists():
            result = json.loads(finished.read_text(encoding="utf-8"))
            print(
                f"--- 이미 끝난 run이라 건너뛴다 (F1={result['eval'].get('eval_f1', 0.0):.4f})",
                flush=True,
            )
            results.append(result)
            write_summary(results, output_root)
            continue

        result = train(
            run_name=experiment.run_name,
            lr=experiment.lr,
            batch_size=experiment.batch_size,
            epochs=experiment.epochs,
            max_length=experiment.max_length,
            output_root=output_root,
            save_steps=save_steps,
            save_total_limit=save_total_limit,
        )
        write_log_history(experiment.run_name, result["log_history"], output_root)
        results.append(result)

        f1 = float(result["eval"].get("eval_f1", 0.0))
        print(
            f"--- {experiment.run_name}: F1={f1:.4f} "
            f"PS_recall={result['eval'].get('eval_ps_recall', 0.0):.4f}",
            flush=True,
        )

        if index == 0 and stop_on_low_f1 and f1 < MIN_ACCEPTABLE_F1:
            print(
                f"\n[중단] F1 {f1:.4f} < {MIN_ACCEPTABLE_F1}. 학습 설정 오류를 "
                f"의심하고 점검할 것. 나머지 run은 돌리지 않는다.",
                flush=True,
            )
            break

        write_summary(results, output_root)

    if results:
        summary = write_summary(results, output_root)
        print(f"\n요약: {summary}", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="KLUE-NER 베이스라인 실험")
    parser.add_argument("--only", action="append", help="특정 run만 실행 (반복 지정 가능)")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--no-stop-on-low-f1", action="store_true")
    parser.add_argument(
        "--save-steps",
        type=int,
        default=0,
        help="N스텝마다 체크포인트. 코랩처럼 세션이 끊길 수 있는 환경에서 켠다.",
    )
    parser.add_argument("--save-total-limit", type=int, default=1)
    parser.add_argument("--rerun-completed", action="store_true")
    args = parser.parse_args()

    selected = EXPERIMENTS
    if args.only:
        names = set(args.only)
        selected = tuple(e for e in EXPERIMENTS if e.run_name in names)
        unknown = names - {e.run_name for e in EXPERIMENTS}
        if unknown:
            parser.error(f"모르는 run: {sorted(unknown)}")

    results = run(
        selected,
        args.output_root,
        stop_on_low_f1=not args.no_stop_on_low_f1,
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        skip_completed=not args.rerun_completed,
    )
    print(
        json.dumps(
            [
                {
                    "run": r["run_name"],
                    **{k: v for k, v in r["eval"].items() if "f1" in k or "recall" in k},
                }
                for r in results
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
