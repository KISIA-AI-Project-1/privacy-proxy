"""데이터셋을 실제 L2~L8 파이프라인에 돌려 결과를 jsonl로 남긴다.

--l7 echo: L7 대신 가명 프롬프트를 그대로 응답으로 흘려보냄(왕복·누수 측정, LLM 호출 없음).
--l7 real --model <모델>: 같은 프롬프트를 두 경로로 보냄.
   가명 경로 = 프록시 전체(L2~L8) / 원본 경로 = 가명처리 없이 같은 L7 함수로 원문 전송.
   두 경로 모두 같은 L7 코드(시스템 프롬프트 포함)를 거치므로 조건 차이는 가명처리뿐.
   키·엔드포인트는 .env와 같은 환경변수(CLAUDE_API_KEY, CLAUDE_API_BASE_URL, CLAUDE_API_FORMAT 등).
   분당 호출 제한이 있으면 --sleep <초>로 레코드 사이에 쉼.
   --out 파일이 이미 있으면 두 경로 모두 성공한 id는 건너뛰고 실패한 것만 다시 돌림(뒤에 덧붙임).

PYTHONPATH=src:. uv run --extra detection python eval/run.py --data <in.jsonl> --out <out.jsonl>
NER은 항상 켬(프록시 구성 요소). 모델 경로는 L4_NER_MODEL_PATH로 바꿀 수 있음.
"""

import argparse
import asyncio
import json
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

os.environ["L4_NER_ENABLED"] = "true"
os.environ.setdefault("L4_NER_MODEL_PATH", "outputs/klue-ner-base-e3/model")

from cost import Budget

from privacy_proxy import pipeline
from privacy_proxy.adapters import AdapterRouter
from privacy_proxy.config import get_settings
from privacy_proxy.schemas import ProxyContext, UserContext
from upstream.llm_client import call_gemini_l7


async def echo_l7(context: ProxyContext) -> ProxyContext:
    body = context.reconstructed_body or {}
    text = context.anonymized_prompt or body["messages"][0]["content"]

    async def chunks() -> AsyncIterator[str]:
        for i in range(0, len(text), 7):  # 청크 경계에 토큰이 걸리게 일부러 잘게 자름
            yield text[i : i + 7]

    context.llm_raw_response = chunks()
    return context


def make_body(model: str, prompt: str) -> dict[str, Any]:
    if model.startswith("gemini"):
        return {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
    return {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }


async def drain(stream: Any) -> str:
    return "".join([c async for c in stream])


async def original_path(body: dict[str, Any], user: UserContext, l7: Any) -> dict[str, Any]:
    """가명처리 없이 같은 L7 함수로 원문을 보낸다."""
    ctx = ProxyContext(user=user, user_role=user.role)
    ctx.parsed_request = AdapterRouter.get_adapter(body).parse(body)
    ctx.reconstructed_body = body
    ctx = await l7(ctx)
    answer = None
    if ctx.status == "success" and ctx.llm_raw_response is not None:
        try:
            answer = await drain(ctx.llm_raw_response)
        except Exception:
            ctx.status = "failed"
    return {"orig_status": ctx.status, "orig_error": ctx.error, "orig_answer": answer}


async def run_one(rec: dict[str, Any], model: str, user: UserContext, l7: Any) -> dict[str, Any]:
    body = make_body(model, rec["prompt"])
    ctx = await pipeline.run_privacy_pipeline(body, user)
    restored = None
    if ctx.status == "success" and ctx.final_response is not None:
        try:
            restored = await drain(ctx.final_response)
        except Exception:
            ctx.status = "failed"
    return {
        "id": rec["id"],
        "status": ctx.status,
        "error": ctx.error,
        "payload": json.dumps(ctx.reconstructed_body, ensure_ascii=False)
        if ctx.reconstructed_body
        else None,
        "anonymized": ctx.anonymized_prompt,
        "restored": restored,
        "detected": [
            {"start": d.start_idx, "end": d.end_idx, "type": str(d.entity_type), "source": d.source}
            for d in ctx.detected_entities
        ],
        "outcomes": [o.model_dump() for o in ctx.entity_outcomes],
        **await original_path(make_body(model, rec["prompt"]), user, l7),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--l7", choices=["echo", "real"], default="echo")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--sleep", type=float, default=0, help="레코드 사이 대기(초), 분당 호출 제한용")
    ap.add_argument(
        "--budget", type=float, default=5.0, help="Claude 누적 비용 상한(USD, 원장 기준)"
    )
    ap.add_argument("--ledger", default="~/eval-data/claude_cost.jsonl")
    a = ap.parse_args()

    l7 = echo_l7 if a.l7 == "echo" else call_gemini_l7
    pipeline.call_gemini_l7 = l7
    user = UserContext(user_id="eval", department="eval", role="employee", allowed_models=[a.model])

    git = ["git", "rev-parse", "--short", "HEAD"]
    commit = subprocess.run(git, capture_output=True, text=True).stdout.strip()  # noqa: S603
    if not get_settings().l4_ner_enabled:
        raise SystemExit("NER이 꺼져 있음")
    meta = {"commit": commit, "l7": a.l7, "model": a.model, "ner": True}

    budget = Budget(a.ledger, a.model, a.budget) if a.l7 == "real" else None
    recs = [json.loads(line) for line in Path(a.data).read_text(encoding="utf-8").splitlines()]
    out = Path(a.out)
    done = set()
    if out.exists():
        rows = map(json.loads, out.read_text(encoding="utf-8").splitlines())
        done = {
            r["id"] for r in rows if r["status"] == r.get("orig_status", "success") == "success"
        }
    with out.open("a", encoding="utf-8") as f:
        for i, rec in enumerate(recs):
            if rec["id"] in done:
                continue
            if budget and budget.over():
                raise SystemExit(f"예산 상한 도달: ${budget.spent():.3f} >= ${a.budget}")
            row = {**meta, **await run_one(rec, a.model, user, l7)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            usd = budget.record(f"run:{rec['id']}") if budget else 0.0
            print(
                f"[{i + 1}/{len(recs)}] {rec['id']} {row['status']} {row['orig_status']} ${usd:.3f}",
                flush=True,
            )
            await asyncio.sleep(a.sleep)


if __name__ == "__main__":
    asyncio.run(main())
