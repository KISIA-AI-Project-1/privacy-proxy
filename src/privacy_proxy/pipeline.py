from typing import Any

from audit.logger import audit_log_l9
from privacy_proxy.adapters import AdapterRouter
from privacy_proxy.schemas import ProxyContext, TextSegment, UserContext
from restore.restorer import restore_l8
from upstream.llm_client import call_gemini_l7

from .mock_layers import (
    mock_l3_detection,
    mock_l4_detection_ecommerce,
    mock_l5_risk_scoring,
    mock_l6_vault_tokenization,
)


async def run_privacy_pipeline(body: dict[str, Any], user: UserContext) -> ProxyContext:
    """
    [L1~L9 통합 오케스트레이션]
    1. L2: 들어온 JSON 포맷(OpenAI/Claude/Gemini) 자동 판별 및 파싱 -> TextSegment 추출
    2. L3~L6: 파이프라인 처리 (탐지, 위험도, 가명화)
    3. L2: 가명화된 텍스트로 원본 JSON 구조 복원 (rebuild)
    4. L7~L9: LLM 호출, 복원, 감사 로깅
    """
    if user is None:
        user = UserContext(user_id="test_user", role="user")

    context = ProxyContext(user=user, user_role=user.role)

    if isinstance(body, str):
        body = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": body}],
        }

    # [L2] 요청 파싱 (JSON -> TextSegment 리스트)
    try:
        adapter = AdapterRouter.get_adapter(body)
        parsed = adapter.parse(body)
        context.parsed_request = parsed

        # 기존 mock_layers 하위 호환용 (세그먼트들의 텍스트를 raw_prompt에 이어붙여 전달)
        context.raw_prompt = "\n".join(seg.text for seg in parsed.segments)
    except Exception as e:
        context.status = "failed"
        context.error = f"L2 Parsing Error: {e!s}"
        return context

    # [L3 ~ L5] 탐지 및 위험도 평가
    if context.status == "success":
        context = await mock_l3_detection(context)

    if context.status == "success":
        context = await mock_l4_detection_ecommerce(context)

    if context.status == "success":
        context = await mock_l5_risk_scoring(context)

    # [L6] 가명화 (토큰화)
    if context.status == "success":
        context = await mock_l6_vault_tokenization(context)

    # [L2 재조립] 가명화된 내용으로 원본 JSON 복원
    if context.status == "success":
        try:
            processed_segments: list[TextSegment] = []
            for seg in parsed.segments:
                replaced_text = context.anonymized_prompt if context.anonymized_prompt else seg.text
                processed_segments.append(
                    TextSegment(
                        segment_id=seg.segment_id,
                        path=seg.path,
                        role=seg.role,
                        text=replaced_text,
                    )
                )

            context.reconstructed_body = adapter.rebuild(parsed, processed_segments)
        except Exception as e:
            context.status = "failed"
            context.error = f"L2 Rebuild Error: {e!s}"
            return context

    # [L7 ~ L9] LLM 호출, 응답 복원, 감사 로그
    if context.status == "success":
        context = await call_gemini_l7(context)

    if context.status == "success":
        context = await restore_l8(context)

    context = await audit_log_l9(context)

    return context
