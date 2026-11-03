"""masked_star 비교 경로: 프록시가 가린 스팬과 같은 위치를 ***로 지워 원본 경로와 같은 L7로 보낸다.

가명 경로(토큰화+역매핑)와 같은 탐지 결과를 쓰고 처리 방식만 다르게 해서,
"값을 지우면 답변 품질이 떨어지는데 토큰화는 덜 떨어진다"를 비교하려는 용도.
run.py --l7 real 결과에서 두 경로 모두 성공한 레코드만 대상. 이미 성공한 id는 건너뜀.

PYTHONPATH=src:. uv run --extra detection python eval/masked.py \
  --data <in.jsonl> --run <run_real.jsonl> --out <masked.jsonl> --model <L7 모델> [--sleep 4]
"""

import argparse
import asyncio
import json
from pathlib import Path

from cost import Budget
from run import make_body, original_path
from score import CHANGED

from privacy_proxy.schemas import UserContext
from upstream.llm_client import call_gemini_l7


def mask(prompt: str, outcomes: list[dict]) -> str:
    spans = sorted((o["start_idx"], o["end_idx"]) for o in outcomes if o["action"] in CHANGED)
    out, pos = [], 0
    for s, e in spans:
        if s < pos:  # 겹치면 앞 스팬에 합침
            s = pos
        if s >= e:
            continue
        out += [prompt[pos:s], "***"]
        pos = e
    return "".join(out) + prompt[pos:]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--sleep", type=float, default=0)
    ap.add_argument(
        "--budget", type=float, default=5.0, help="Claude 누적 비용 상한(USD, 원장 기준)"
    )
    ap.add_argument("--ledger", default="~/eval-data/claude_cost.jsonl")
    a = ap.parse_args()

    data = {
        r["id"]: r for r in map(json.loads, Path(a.data).read_text(encoding="utf-8").splitlines())
    }
    rows = [json.loads(line) for line in Path(a.run).read_text(encoding="utf-8").splitlines()]
    runs = [
        r
        for r in {r["id"]: r for r in rows}.values()
        if r["status"] == r["orig_status"] == "success"
    ]
    budget = Budget(a.ledger, a.model, a.budget)
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {
            x["id"]
            for x in map(json.loads, out.read_text(encoding="utf-8").splitlines())
            if x["masked_status"] == "success"
        }
    user = UserContext(user_id="eval", department="eval", role="employee", allowed_models=[a.model])
    with out.open("a", encoding="utf-8") as f:
        for i, r in enumerate(runs):
            if r["id"] in done:
                continue
            if budget.over():
                raise SystemExit(f"예산 상한 도달: ${budget.spent():.3f} >= ${a.budget}")
            prompt = mask(data[r["id"]]["prompt"], r["outcomes"])
            res = await original_path(make_body(a.model, prompt), user, call_gemini_l7)
            row = {
                "id": r["id"],
                "commit": r["commit"],
                "model": a.model,
                "masked_prompt": prompt,
                "masked_status": res["orig_status"],
                "masked_error": res["orig_error"],
                "masked_answer": res["orig_answer"],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            usd = budget.record(f"masked:{r['id']}")
            print(f"[{i + 1}/{len(runs)}] {r['id']} {row['masked_status']} ${usd:.3f}", flush=True)
            await asyncio.sleep(a.sleep)


if __name__ == "__main__":
    asyncio.run(main())
