"""⑥ LLM-as-a-Judge: 자유서술 과제의 원본 답변 vs 복원 답변 의미 동치 판정.

A/B 위치를 바꿔 2회 판정, 두 번이 같으면 그 라벨, 다르면 '불일치'.
판정 모델은 L7 답변 모델과 다른 것을 쓸 것(--model).
키·엔드포인트는 L7과 같은 환경변수. CLAUDE_API_FORMAT=openai(게이트웨이)면 모든 모델이 그 경로로 감.
--out이 이미 있으면 끝난 id는 건너뜀. 대상은 자유서술 중 --limit건을 seed 고정 무작위 추출(그룹 편중 방지).
Claude 판정 모델이면 cost.py 원장으로 --budget 상한 적용.

PYTHONPATH=src:. uv run --extra detection python eval/judge.py --data <in.jsonl> --run <run.jsonl> \
    --model <판정 모델> --out <judge.jsonl>
"""

import argparse
import asyncio
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cost import Budget

from upstream.llm_client import (
    _claude_chat_completions_url,
    _stream_claude,
    _stream_gemini,
    _stream_openai,
)

LABELS = ("동치", "경미한 차이", "의미 다름")
PROMPT = """다음은 같은 요청에 대한 두 답변이다. 두 답변이 전달하는 의미와 판단이 같은지 판정하라.
숫자·금액·날짜·이름·식별자·부정 표현·결론이 하나라도 다르면 '의미 다름'이다.
문체·어순·길이·인사말 차이만 있으면 '동치', 사소한 정보가 빠지거나 더해졌지만 결론과 핵심 사실이 같으면 '경미한 차이'다.

[요청]
{prompt}

[답변 A]
{a}

[답변 B]
{b}

JSON 한 줄만 출력: {{"label": "동치" 또는 "경미한 차이" 또는 "의미 다름", "reason": "한 문장"}}"""


async def ask(model: str, text: str) -> str:
    msgs = [{"role": "user", "content": text}]
    if os.getenv("CLAUDE_API_FORMAT", "anthropic") == "openai":
        body = {"model": model, "max_tokens": 300, "temperature": 0, "messages": msgs}
        stream = _stream_openai(
            body, os.environ["CLAUDE_API_KEY"], api_url=_claude_chat_completions_url()
        )
    elif model.startswith("claude"):
        body = {"model": model, "max_tokens": 300, "temperature": 0, "messages": msgs}
        stream = _stream_claude(body, os.environ["CLAUDE_API_KEY"])
    elif model.startswith("gemini"):
        gbody: dict[str, Any] = {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0},
        }
        stream = _stream_gemini(gbody, os.environ["GEMINI_API_KEY"])
    else:
        body = {"model": model, "max_tokens": 300, "temperature": 0, "messages": msgs}
        stream = _stream_openai(body, os.environ["OPENAI_API_KEY"])
    return "".join([c async for c in stream])


def parse_label(raw: str) -> str:
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            label = json.loads(m.group(0)).get("label")
            if label in LABELS:
                return str(label)
        except json.JSONDecodeError:
            pass
    found = [x for x in LABELS if x in raw]
    return found[0] if len(found) == 1 else "파싱실패"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0)
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--ledger", default="~/eval-data/claude_cost.jsonl")
    a = ap.parse_args()

    data = {
        r["id"]: r for r in map(json.loads, Path(a.data).read_text(encoding="utf-8").splitlines())
    }
    rows = [json.loads(line) for line in Path(a.run).read_text(encoding="utf-8").splitlines()]
    runs = [
        r
        for r in {r["id"]: r for r in rows}.values()
        if data[r["id"]]["task"]["type"] == "자유서술"
        and r.get("orig_answer")
        and r.get("restored")
    ]
    runs = random.Random(a.seed).sample(runs, min(a.limit, len(runs)))  # noqa: S311
    budget = Budget(a.ledger, a.model, a.budget)

    out = Path(a.out)
    done = set()
    if out.exists():
        done = {json.loads(line)["id"] for line in out.read_text(encoding="utf-8").splitlines()}
    with out.open("a", encoding="utf-8") as f:
        for r in runs:
            if r["id"] in done:
                continue
            if budget.over():
                raise SystemExit(f"예산 상한 도달: ${budget.spent():.3f}")
            p = data[r["id"]]["prompt"]
            raw1 = await ask(a.model, PROMPT.format(prompt=p, a=r["orig_answer"], b=r["restored"]))
            raw2 = await ask(a.model, PROMPT.format(prompt=p, a=r["restored"], b=r["orig_answer"]))
            l1, l2 = parse_label(raw1), parse_label(raw2)
            row = {
                "id": r["id"],
                "judge": a.model,
                "l7_model": r.get("model"),
                "first": l1,
                "swapped": l2,
                "final": l1 if l1 == l2 else "불일치",
                "raw": [raw1, raw2],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            budget.record(f"judge:{r['id']}")
            print(r["id"], l1, l2, flush=True)
            await asyncio.sleep(a.sleep)

    results = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    by: dict[str, Counter[str]] = defaultdict(Counter)
    for j in results:
        by[data[j["id"]]["group"]][j["final"]] += 1
    print(f"\n⑥ Judge ({a.model}) 최종 라벨(두 번 일치할 때만, 아니면 불일치)")
    for grp, c in sorted(by.items()):
        n = sum(c.values())
        print(
            f"  {grp:<18} n={n} " + " ".join(f"{k}={c[k]}" for k in (*LABELS, "불일치", "파싱실패"))
        )


if __name__ == "__main__":
    asyncio.run(main())
