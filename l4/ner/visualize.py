"""실험 결과 시각화. matplotlib만 쓴다 (wandb 등 외부 도구 없음).

uv run python -m l4.ner.visualize --output-root outputs
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # 헤드리스 환경(WSL, CI)에서 화면 없이 저장만 한다
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

from l4.ner.labels import L4_ENTITY_TYPES

FIGURE_DIR = "figures"


def _setup_korean_font() -> None:
    """한글 라벨이 깨지지 않게 폰트를 잡는다. 없으면 경고만 하고 진행한다.

    CI·WSL 기본 이미지엔 한글 폰트가 없어 제목이 두부(□)로 나온다.
    ``apt install fonts-nanum`` 또는 ``~/.local/share/fonts`` 에 ttf를 두면 잡힌다.
    """
    for family in ("NanumGothic", "NanumBarunGothic", "Noto Sans CJK KR", "Malgun Gothic"):
        try:
            path = fm.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        plt.rcParams["font.family"] = fm.FontProperties(fname=path).get_name()
        plt.rcParams["axes.unicode_minus"] = False
        return

    patterns = (
        "/usr/share/fonts/**/Nanum*.ttf",
        str(Path.home() / ".local/share/fonts/*.ttf"),
        str(Path.home() / ".fonts/*.ttf"),
    )
    for pattern in patterns:
        hits = glob.glob(pattern, recursive=True)
        if hits:
            fm.fontManager.addfont(hits[0])
            plt.rcParams["font.family"] = fm.FontProperties(fname=hits[0]).get_name()
            plt.rcParams["axes.unicode_minus"] = False
            return

    print("경고: 한글 폰트 없음 — 라벨이 깨질 수 있다 (apt install fonts-nanum)")


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


def plot_hparam_comparison(summary: list[dict[str, str]], target: Path) -> bool:
    """1차 학습 4개 run의 하이퍼파라미터별 성능. 채택 run(base-e3)을 강조한다."""
    if not summary:
        return False

    metrics = [("f1", "entity F1"), ("PS_recall", "PS recall"), ("LC_f1", "LC F1")]
    runs = [row["run_name"] for row in summary]

    figure, axes = plt.subplots(figsize=(9, 5))
    width = 0.25
    positions = range(len(runs))
    for index, (key, label) in enumerate(metrics):
        series = [_as_float(row.get(key)) or 0.0 for row in summary]
        bars = axes.bar([p + index * width for p in positions], series, width, label=label)
        for rect, value in zip(bars, series, strict=True):
            axes.text(
                rect.get_x() + rect.get_width() / 2,
                value + 0.005,
                f"{value:.4f}",
                ha="center",
                fontsize=7,
            )

    subtitles = [
        f"{row['run_name']}\nlr={row['lr']} · ep={row['epochs']} · len={row['max_length']}"
        for row in summary
    ]
    axes.set_xticks([p + width for p in positions])
    axes.set_xticklabels(subtitles, fontsize=8)
    axes.set_ylim(0.75, 0.95)
    axes.set_ylabel("score")
    axes.set_title(
        "KLUE-NER 1차 학습 — 하이퍼파라미터별 성능\n"
        "채택: klue-ner-base-e3 (F1 미세 손실 감수, PS recall 우선)"
    )
    axes.grid(axis="y", alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return True


def plot_alignment_effect(eval_path: Path, target: Path) -> bool:
    """채택 모델에 alignment.py(조사 경계 중재) 적용 전/후 성능 비교."""
    if not eval_path.exists():
        return False
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    before, after = data["before"], data["after"]
    ceiling = data.get("ceiling_f1")

    keys = [("f1", "entity F1"), ("PS_recall", "PS recall"), ("PS_f1", "PS F1"), ("LC_f1", "LC F1")]

    figure, axes = plt.subplots(figsize=(9, 5))
    width = 0.38
    positions = range(len(keys))
    before_vals = [before[key] for key, _ in keys]
    after_vals = [after[key] for key, _ in keys]

    b1 = axes.bar([p - width / 2 for p in positions], before_vals, width, label="적용 전")
    b2 = axes.bar([p + width / 2 for p in positions], after_vals, width, label="적용 후")
    for bars, vals in ((b1, before_vals), (b2, after_vals)):
        for rect, value in zip(bars, vals, strict=True):
            axes.text(
                rect.get_x() + rect.get_width() / 2,
                value + 0.004,
                f"{value:.4f}",
                ha="center",
                fontsize=7,
            )
    for index, (key, _) in enumerate(keys):
        delta = after[key] - before[key]
        axes.text(
            index,
            max(before[key], after[key]) + 0.018,
            f"{delta:+.4f}",
            ha="center",
            fontsize=8,
            color="green" if delta >= 0 else "red",
        )

    if ceiling is not None:
        axes.axhline(ceiling, ls="--", lw=1, color="gray")
        axes.text(len(keys) - 0.5, ceiling + 0.002, f"평가 상한 {ceiling}", ha="right", fontsize=8)

    axes.set_xticks(list(positions))
    axes.set_xticklabels([label for _, label in keys])
    axes.set_ylim(0.75, 1.0)
    axes.set_ylabel("score")
    axes.set_title(
        "klue-ner-base-e3 + alignment.py 적용 전/후 (validation 5,000건, 재학습 없음)\n"
        "조사 경계 중재로 PS recall 회수 — 후처리 한 단계"
    )
    axes.grid(axis="y", alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    return True


def render(output_root: Path) -> list[Path]:
    _setup_korean_font()
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
        ("hparam_comparison.png", lambda p: plot_hparam_comparison(summary, p)),
        (
            "alignment_effect.png",
            lambda p: plot_alignment_effect(
                output_root / "klue-ner-base-e3" / "alignment_eval.json", p
            ),
        ),
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
