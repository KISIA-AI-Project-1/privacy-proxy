"""⑤ BERTScore: 원본 경로 답변 vs 복원 답변(보조 지표, 단독 사용 금지).

idf 가중치·baseline rescale 없는 기본형(토큰 임베딩 greedy cosine 매칭의 F1).
레이어 17은 bert_score 패키지의 roberta-large 기본값을 그대로 씀(klue용으로 튜닝된 값 아님).

PYTHONPATH=src:. uv run --extra detection python eval/bertscore.py --data <in.jsonl> --run <run.jsonl>
"""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModel, AutoTokenizer


def embed(tok: Any, model: Any, text: str, layer: int) -> torch.Tensor:
    enc = tok(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        h = model(**enc, output_hidden_states=True).hidden_states[layer][0, 1:-1]
    return torch.nn.functional.normalize(h, dim=-1)


def f1(a: torch.Tensor, b: torch.Tensor) -> float:
    sim = a @ b.T
    p, r = sim.max(1).values.mean().item(), sim.max(0).values.mean().item()
    return 2 * p * r / (p + r)


def mean_ci(rows: list[tuple[str, float]], reps: int = 2000) -> str:
    by: dict[str, list[float]] = defaultdict(list)
    for c, v in rows:
        by[c].append(v)
    groups = list(by.values())
    rng = random.Random(0)  # noqa: S311
    means = sorted(
        sum(x := [v for g in rng.choices(groups, k=len(groups)) for v in g]) / len(x)
        for _ in range(reps)
    )
    m = sum(v for _, v in rows) / len(rows)
    return f"{m:.4f} boot[{means[int(reps * 0.025)]:.4f}, {means[int(reps * 0.975) - 1]:.4f}] (n={len(rows)})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", default="klue/roberta-large")
    ap.add_argument("--layer", type=int, default=17)
    a = ap.parse_args()

    data = {
        r["id"]: r for r in map(json.loads, Path(a.data).read_text(encoding="utf-8").splitlines())
    }
    rows = [json.loads(line) for line in Path(a.run).read_text(encoding="utf-8").splitlines()]
    runs = list({r["id"]: r for r in rows}.values())

    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModel.from_pretrained(a.model).eval()
    scores: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for r in runs:
        if not r.get("orig_answer") or not r.get("restored"):
            continue
        rec = data[r["id"]]
        s = f1(
            embed(tok, model, r["orig_answer"], a.layer), embed(tok, model, r["restored"], a.layer)
        )
        cl = rec["id"].rsplit("-", 1)[0]
        scores[(rec["group"], rec["task"]["type"])].append((cl, s))
        scores[(rec["group"], "전체")].append((cl, s))

    print(f"⑤ BERTScore F1 ({a.model}, layer {a.layer}, 원본 답변 vs 복원 답변)")
    for (grp, kind), v in sorted(scores.items()):
        print(f"  {grp:<18} {kind:<6} {mean_ci(v)}")


if __name__ == "__main__":
    main()
