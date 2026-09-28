"""FastAPI 앱 진입점.

현재는 부팅과 헬스체크만 한다. L1~L9 라우터는 각 담당자가 붙인다.
실행: uv run uvicorn privacy_proxy.main:app --reload --port 8000
"""

from typing import Any, Literal

import boto3
from fastapi import Depends, FastAPI, HTTPException

from privacy_proxy import __version__
from privacy_proxy.adapters import get_current_user
from privacy_proxy.pipeline import run_privacy_pipeline
from privacy_proxy.schemas import UserContext

s3_client = boto3.client("s3", region_name="ap-northeast-2")
BUCKET_NAME = "privacy-proxy-storage"

app = FastAPI(
    title="privacy-proxy",
    version=__version__,
    description="LLM 프롬프트 개인정보 가명화 프록시",
)


@app.get("/healthz")
async def healthz() -> dict[str, str | Literal["ok"]]:
    """로드밸런서·CI용 헬스체크. 비밀값을 절대 노출하지 않는다."""
    return {"status": "ok", "version": __version__}


@app.post("/v1/chat/completions")
@app.post("/v1/chat")
async def process_chat(
    body: dict[str, Any],
    user: UserContext = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """
    [L1~L9 통합 엔드포인트]
    2. L2~L9 파이프라인 처리 (멀티 벤더 파싱 -> 탐지 -> 가명화 -> 재조립 -> 중계 -> 복원 -> 감사)
    """
    context = await run_privacy_pipeline(body=body, user=user)

    if context.status == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"프라이버시 처리 파이프라인 에러: {context.error}",
        )

    return {
        "status": context.status,
        "session_id": context.session_id,
        "user_id": user.user_id,
        "reconstructed_body": context.reconstructed_body,
        "anonymized_text": context.anonymized_prompt,
        "vault_keys": list(context.vault_mapping.keys()) if context.vault_mapping else [],
        "final_response": context.final_response,
    }


@app.post("/v1/upload-log")
async def upload_log_to_s3(filename: str, content: str) -> dict[str, Any]:
    """S3 버킷으로 마스킹 결과/로그 텍스트를 저장하는 엔드포인트"""
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=f"logs/{filename}",
            Body=content.encode("utf-8"),
        )
        return {"status": "success", "message": f"Successfully uploaded {filename} to S3"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"S3 업로드 실패: {e!s}") from e
