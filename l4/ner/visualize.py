"""실험 결과 시각화. matplotlib만 쓴다 (wandb 등 외부 도구 없음).

uv run python -m l4.ner.visualize --output-root outputs
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # 헤드리스 환경(WSL, CI)에서 화면 없이 저장만 한다
import matplotlib.pyplot as plt

from l4.ner.labels import L4_ENTITY_TYPES

FIGURE_DIR = "figures"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _as_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def plot_f1_curves(output_root: Path, run_names: list[str], target: Path) -> bool:
    """epoch별 F1 곡선. 4개 run을 겹쳐 그린다."""
    figure, axes = plt.subplots(figsize=(8, 5))
    drawn = False

    for run_name in run_names:
        rows = _read_csv(output_root / run_name / "log_history.csv")
        points: list[tuple[float, float]] = []
        for row in rows:
            epoch = _as_float(row.get("epoch"))
            f1 = _as_float(row.get("eval_f1"))
            if epoch is not None and f1 is not None:
                points.append((epoch, f1))
        if not points:
            continue
        epochs = [point[0] for point in points]
        scores = [point[1] for point in points]
        axes.plot(epochs, scores, marker="o", label=run_name)
        drawn = True

    if not drawn:
        plt.close(figure)
        return False

    axes.set_xlabel("epoch")
    axes.set_ylabel("entity F1 (seqeval)")
    axes.set_title("KLUE-NER 1차 학습 — epoch별 엔티티 F1")
    axes.grid(alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return True


def plot_per_tag(summary: list[dict[str, str]], target: Path) -> bool:
    """태그별 P/R/F1 막대. L4가 실제로 쓰는 PS·LC를 강조한다."""
    if not summary:
        return False
    row = summary[0]
    run_name = row["run_name"]

    tags = list(L4_ENTITY_TYPES)
    metrics = ["precision", "recall", "f1"]
    values: list[list[float]] = []
    for metric in metrics:
        values.append([_as_float(row.get(f"{tag}_{metric}")) or 0.0 for tag in tags])

    figure, axes = plt.subplots(figsize=(7, 5))
    width = 0.25
    positions = range(len(tags))
    for index, (metric, series) in enumerate(zip(metrics, values, strict=True)):
        axes.bar([p + index * width for p in positions], series, width, label=metric)
        for p, value in zip(positions, series, strict=True):
            axes.text(p + index * width, value + 0.01, f"{value:.3f}", ha="center", fontsize=8)

    axes.set_xticks([p + width for p in positions])
    axes.set_xticklabels(tags)
    axes.set_ylim(0, 1.05)
    axes.set_ylabel("score")
    axes.set_title(f"태그별 P/R/F1 — {run_name}\n(L4가 쓰는 태그만: PS 인명, LC 지명)")
    axes.grid(axis="y", alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return True


def plot_latency_tradeoff(summary: list[dict[str, str]], target: Path) -> bool:
    """F1 대비 추론 지연시간. len256이 실제로 값어치를 하는지 본다."""
    points: list[tuple[str, float, float]] = []
    for row in summary:
        f1 = _as_float(row.get("f1"))
        latency = _as_float(row.get("latency_p50_s"))
        if f1 is None or latency is None:
            continue
        points.append((row["run_name"], latency * 1000, f1))

    if not points:
        return False

    figure, axes = plt.subplots(figsize=(7, 5))
    for run_name, latency_ms, f1 in points:
        highlight = "len256" in run_name
        axes.scatter(
            latency_ms, f1, s=140 if highlight else 90, marker="D" if highlight else "o", zorder=3
        )
        axes.annotate(
            run_name, (latency_ms, f1), textcoords="offset points", xytext=(8, 6), fontsize=9
        )

    axes.set_xlabel("요청 1건당 추론 지연시간 p50 (ms)")
    axes.set_ylabel("entity F1")
    axes.set_title("지연시간 대비 성능\nL4는 모든 요청에 걸리므로 지연시간이 곧 비용")
    axes.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return True


def render(output_root: Path) -> list[Path]:
    summary = _read_csv(output_root / "summary.csv")
    run_names = [row["run_name"] for row in summary] or [
        path.name for path in sorted(output_root.glob("*/log_history.csv"))
    ]

    figure_dir = output_root / FIGURE_DIR
    figure_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    jobs: list[tuple[str, Any]] = [
        ("f1_curves.png", lambda p: plot_f1_curves(output_root, run_names, p)),
        ("per_tag.png", lambda p: plot_per_tag(summary, p)),
        ("latency_tradeoff.png", lambda p: plot_latency_tradeoff(summary, p)),
    ]
    for filename, draw in jobs:
        path = figure_dir / filename
        if draw(path):
            written.append(path)
            print(f"저장: {path}")
        else:
            print(f"건너뜀: {filename} (데이터 없음)")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="실험 결과 시각화")
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    render(args.output_root)


if __name__ == "__main__":
    main()
