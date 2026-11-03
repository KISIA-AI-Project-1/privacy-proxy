"""원본 경로 재실행 기준선: 같은 원문을 같은 L7에 한 번 더 보내 '원본 vs 원본' 차이를 잰다.

결과 행은 run.py 형식을 따르되 restored 자리에 두 번째 원본 답변을 넣음.
→ score.py(③④)·bertscore.py(⑤)를 그대로 돌리면 가명처리 없이 생기는 L7 자체 변동(노이즈 바닥)이 나옴.
두 경로 모두 성공한 run 레코드만 대상, 이미 성공한 id는 건너뜀.

PYTHONPATH=src:. uv run --extra detection python eval/baseline.py \
  --data <in.jsonl> --run <run_real.jsonl> --out <baseline.jsonl> --model <L7 모델> [--budget 12]
"""

import argparse
import asyncio
import json
from pathlib import Path

from cost import Budget
from run import make_body, original_path

from privacy_proxy.schemas import UserContext
from upstream.llm_client import call_gemini_l7


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--sleep", type=float, default=0)
    ap.add_argument("--budget", type=float, default=12.0)
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
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {
            x["id"]
            for x in map(json.loads, out.read_text(encoding="utf-8").splitlines())
            if x["status"] == "success"
        }
    budget = Budget(a.ledger, a.model, a.budget)
    user = UserContext(user_id="eval", department="eval", role="employee", allowed_models=[a.model])
    with out.open("a", encoding="utf-8") as f:
        for i, r in enumerate(runs):
            if r["id"] in done:
                continue
            if budget.over():
                raise SystemExit(f"예산 상한 도달: ${budget.spent():.3f} >= ${a.budget}")
            res = await original_path(
                make_body(a.model, data[r["id"]]["prompt"]), user, call_gemini_l7
            )
            row = {
                **r,
                "status": res["orig_status"],
                "error": res["orig_error"],
                "restored": res["orig_answer"],
                "baseline": "원본 재실행",
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            usd = budget.record(f"baseline:{r['id']}")
            print(f"[{i + 1}/{len(runs)}] {r['id']} {row['status']} ${usd:.3f}", flush=True)
            await asyncio.sleep(a.sleep)


if __name__ == "__main__":
    asyncio.run(main())
