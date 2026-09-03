"""FastAPI 앱 진입점.

현재는 부팅과 헬스체크만 한다. L1~L9 라우터는 각 담당자가 붙인다.
실행: uv run uvicorn privacy_proxy.main:app --reload --port 8000
"""

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from privacy_proxy import __version__
from privacy_proxy.pipeline import run_privacy_pipeline

app = FastAPI(
    title="privacy-proxy",
    version=__version__,
    description="LLM 프롬프트 개인정보 가명화 프록시",
)


@app.get("/healthz")
async def healthz() -> dict[str, str | Literal["ok"]]:
    """로드밸런서·CI용 헬스체크. 비밀값을 절대 노출하지 않는다."""
    return {"status": "ok", "version": __version__}


class PromptRequest(BaseModel):
    text: str


@app.post("/v1/chat")
async def process_prompt(request: PromptRequest) -> dict[str, Any]:
    """
    사용자의 질문을 받아 L1~L9 파이프라인을 통과시킵니다.
    """
    # 1. 컨베이어 벨트(파이프라인)에 원본 텍스트 투입
    context = await run_privacy_pipeline(request.text)

    # 2. 에러 발생 시 서버 에러 반환
    if context.status == "failed":
        raise HTTPException(status_code=500, detail="프라이버시 처리 파이프라인 에러")

    # 3. 임시 결과물 반환
    return {
        "status": context.status,
        "original_text": context.raw_prompt,
        "anonymized_text": context.anonymized_prompt,
        "vault_keys_generated": list(context.vault_mapping.keys()) if context.vault_mapping else [],
    }
