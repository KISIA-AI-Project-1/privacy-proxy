"""FastAPI 앱 진입점.

L1 인증 후 L2~L9 파이프라인을 실행한다.
응답 스트림을 모두 읽어 JSON 형식으로 반환한다.
시연 모드에서는 단계별 결과를 추가로 제공한다.

실행:
uv run uvicorn privacy_proxy.main:app --reload --port 8000
"""

from collections.abc import AsyncIterable
from typing import Any, Literal, cast

from fastapi import Depends, FastAPI, HTTPException
from starlette.concurrency import run_in_threadpool

from privacy_proxy import __version__
from privacy_proxy.adapters import get_current_user
from privacy_proxy.config import get_settings
from privacy_proxy.pipeline import _get_l3_service, _get_l6_tokenizer, run_privacy_pipeline
from privacy_proxy.schemas import ProxyContext, UserContext

app = FastAPI(
    title="privacy-proxy",
    version=__version__,
    description="LLM 프롬프트 개인정보 가명화 프록시",
)


@app.get("/healthz")
async def healthz() -> dict[str, str | Literal["ok"]]:
    """로드밸런서·CI용 헬스체크. 비밀값을 노출하지 않는다."""
    return {"status": "ok", "version": __version__}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Load and warm detection/Vault before reporting readiness."""
    try:
        if not get_settings().proxy_api_key.get_secret_value().strip():
            raise ValueError("PROXY_API_KEY_REQUIRED")
        l3 = await run_in_threadpool(_get_l3_service)
        await run_in_threadpool(l3.analyze, raw_prompt="시연 준비 확인", segment_id="warmup")
        await run_in_threadpool(_get_l6_tokenizer)
    except Exception:
        raise HTTPException(status_code=503, detail="PRIVACY_DEPENDENCIES_NOT_READY") from None
    return {"status": "ready"}


def require_demo_mode() -> None:
    """시연 모드가 아니면 시연용 요청을 거절한다."""
    if not get_settings().demo_mode:
        raise HTTPException(
            status_code=404,
            detail="Not Found",
        )


async def _run_and_collect(
    body: dict[str, Any],
    user: UserContext,
) -> tuple[ProxyContext, str]:
    """파이프라인을 실행하고 복원된 응답 스트림을 모은다."""
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

    return context, "".join(chunks)


@app.post("/v1/chat/completions")
@app.post("/v1/chat")
async def process_chat(
    body: dict[str, Any],
    user: UserContext = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """기존 형식으로 파이프라인 처리 결과를 반환한다."""
    context, final_text = await _run_and_collect(body, user)

    return {
        "status": context.status,
        "session_id": context.session_id,
        "user_id": user.user_id,
        "reconstructed_body": context.reconstructed_body,
        "anonymized_text": context.anonymized_prompt,
        "vault_keys": (list(context.vault_mapping.keys()) if context.vault_mapping else []),
        "final_response": final_text,
    }


@app.post(
    "/v1/demo/chat",
    dependencies=[Depends(require_demo_mode)],
)
async def process_demo_chat(
    body: dict[str, Any],
    user: UserContext = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """시연 모드에서 인증된 사용자에게 단계별 결과를 반환한다."""
    context, final_text = await _run_and_collect(body, user)

    if not context.upstream_request_body:
        raise HTTPException(
            status_code=500,
            detail="DEMO_UPSTREAM_REQUEST_MISSING",
        )

    parsed = context.parsed_request

    # L5의 중복·겹침 처리 이후 남은 탐지 결과를 제공한다.
    detections = [
        {
            "segment_id": entity.segment_id,
            "entity_type": str(entity.entity_type),
            "start_idx": entity.start_idx,
            "end_idx": entity.end_idx,
            "original_value": entity.original_value,
            "confidence": entity.confidence,
            "source": entity.source,
            "tier": str(entity.tier),
        }
        for entity in context.detected_entities
    ]

    # 복원 매핑 전체 대신 토큰과 엔티티 종류만 제공한다.
    tokens = [
        {
            "token": token,
            "entity_type": entity_type,
        }
        for token, entity_type in context.token_types.items()
    ]

    return {
        "status": context.status,
        "session_id": context.session_id,
        "vendor": parsed.vendor if parsed is not None else None,
        "model": parsed.model if parsed is not None else None,
        "input": {
            "text": context.raw_prompt,
        },
        "detection": {
            "coordinate_basis": "raw_prompt",
            "selection_stage": "after_l5_overlap_resolution",
            "count": len(detections),
            "entities": detections,
        },
        "risk": {
            "score": context.risk_score,
            "level": context.risk_level,
            "reasons": context.risk_reasons,
            "policy_action": context.policy_action,
            # 항목별 처리(토큰화/일반화/유지). 위치로 detection.entities 와 연결한다.
            "entity_policies": [p.model_dump() for p in context.entity_policies],
            "policy_scope": "request",
        },
        "anonymization": {
            "text": context.anonymized_prompt,
            "tokens": tokens,
            "entity_actions": context.entity_actions,
        },
        "upstream": {
            "request_body": context.upstream_request_body,
        },
        "response": {
            "text": final_text,
            "before_restore": context.upstream_response_text,
        },
        "latency_ms": dict(context.latency_ms),
    }
