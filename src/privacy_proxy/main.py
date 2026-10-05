"""FastAPI 앱 진입점.

L1 인증 후 L2~L9 파이프라인을 실행한다.
응답 스트림을 모두 읽어 기존 JSON 형식으로 반환한다.

실행:
uv run uvicorn privacy_proxy.main:app --reload --port 8000
"""

from collections.abc import AsyncIterable
from typing import Any, Literal, cast

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
    """로드밸런서·CI용 헬스체크. 비밀값을 노출하지 않는다."""
    return {"status": "ok", "version": __version__}


@app.post("/v1/chat/completions")
@app.post("/v1/chat")
async def process_chat(
    body: dict[str, Any],
    user: UserContext = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """L1~L9 통합 엔드포인트.

    인증 후 파싱, 탐지, 위험 평가, 가명화, 재조립,
    LLM 중계, 복원과 감사 기록을 수행한다.
    """
    context = await run_privacy_pipeline(body=body, user=user)

    if context.status != "success":
        raise HTTPException(
            status_code=500,
            detail=(f"프라이버시 처리 파이프라인 에러: {context.error or 'PIPELINE_FAILED'}"),
        )

    if context.final_response is None:
        context.status = "failed"
        context.error = "FINAL_RESPONSE_MISSING"
        raise HTTPException(
            status_code=500,
            detail="프라이버시 처리 파이프라인 에러: FINAL_RESPONSE_MISSING",
        )

    # 비동기 스트림 객체를 직접 JSON에 넣지 않고,
    # 실제로 읽어서 완성된 응답 문자열을 만든다.
    chunks: list[str] = []

    try:
        stream = cast(
            AsyncIterable[str],
            context.final_response,
        )

        async for chunk in stream:
            chunks.append(chunk)

    except Exception as exc:
        # L7·L8·L9가 기록한 오류 코드를 유지한다.
        if context.status == "success":
            context.status = "failed"
            context.error = "RESPONSE_STREAM_FAILED"

        raise HTTPException(
            status_code=502,
            detail=(f"LLM 응답 처리 에러: {context.error or 'RESPONSE_STREAM_FAILED'}"),
        ) from exc

    if context.status != "success":
        raise HTTPException(
            status_code=502,
            detail=(f"LLM 응답 처리 에러: {context.error or 'RESPONSE_STREAM_FAILED'}"),
        )

    return {
        "status": context.status,
        "session_id": context.session_id,
        "user_id": user.user_id,
        "reconstructed_body": context.reconstructed_body,
        "anonymized_text": context.anonymized_prompt,
        "vault_keys": (list(context.vault_mapping.keys()) if context.vault_mapping else []),
        "final_response": "".join(chunks),
    }


@app.post("/v1/upload-log")
async def upload_log_to_s3(filename: str, content: str) -> dict[str, Any]:
    """S3 버킷으로 마스킹 결과·로그 텍스트를 저장한다."""
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=f"logs/{filename}",
            Body=content.encode("utf-8"),
        )
        return {
            "status": "success",
            "message": f"Successfully uploaded {filename} to S3",
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="S3 업로드 실패",
        ) from exc
