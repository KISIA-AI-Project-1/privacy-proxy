import os
from typing import TYPE_CHECKING, Any

from l4.recognizers import (
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)

from audit.logger import audit_log_l9
from privacy_proxy.adapters import AdapterRouter
from privacy_proxy.risk import run_l5_risk_scoring
from privacy_proxy.schemas import (
    DetectedPII,
    ProxyContext,
    TextSegment,
    UserContext,
)
from privacy_proxy.vault import Tokenizer, VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore
from restore.restorer import restore_l8
from upstream.llm_client import call_gemini_l7

if TYPE_CHECKING:
    from privacy_proxy.l3.service import L3AnalyzerService


_l3_service: "L3AnalyzerService | None" = None
_l6_tokenizer: Tokenizer | None = None


def _get_l3_service() -> "L3AnalyzerService":
    global _l3_service

    if _l3_service is None:
        from privacy_proxy.l3.service import L3AnalyzerService

        _l3_service = L3AnalyzerService()

    return _l3_service


def _get_l6_tokenizer() -> Tokenizer:
    """로컬 통합 확인용 메모리 저장소와 실제 L6를 초기화한다."""
    global _l6_tokenizer

    if _l6_tokenizer is None:
        crypto = VaultCrypto(os.urandom(32))
        store = InMemoryVaultStore(crypto)
        _l6_tokenizer = Tokenizer(
            store,
            crypto,
            strict=True,
        )

    return _l6_tokenizer


def _to_detected_pii(
    det: Any,
    offset_base: int,
) -> DetectedPII:
    """입력 문자열 기준 탐지 위치를 전체 원문 기준으로 변환한다."""
    return DetectedPII(
        segment_id=det.segment_id,
        start_idx=det.start_idx + offset_base,
        end_idx=det.end_idx + offset_base,
        entity_type=det.entity_type,
        confidence=det.confidence,
        source=det.source,
        tier=det.tier,
        original_value=det.original_value,
        normalized=det.normalized,
    )


async def run_privacy_pipeline(
    body: dict[str, Any] | str,
    user: UserContext,
) -> ProxyContext:
    context = ProxyContext(user=user, user_role=user.role)

    if isinstance(body, str):
        body = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": body}],
        }

    # [L2] 요청 파싱
    try:
        adapter = AdapterRouter.get_adapter(body)
        parsed = adapter.parse(body)

        context.parsed_request = parsed
        context.raw_prompt = "\n".join(seg.text for seg in parsed.segments)

    except Exception:
        context.status = "failed"
        context.error = "L2_PARSING_FAILED"
        return await audit_log_l9(context)

    # 현재 재조립 방식은 단일 세그먼트만 지원한다.
    if len(parsed.segments) > 1:
        context.status = "failed"
        context.error = "MULTI_SEGMENT_NOT_SUPPORTED"
        return await audit_log_l9(context)

    if not parsed.segments:
        context.status = "failed"
        context.error = "L2_PARSING_FAILED"
        return await audit_log_l9(context)

    # 현재 L2가 추출하지 못하는 텍스트 형식은 전송하지 않는다.
    try:
        if parsed.vendor in {"openai", "anthropic"}:
            messages = body.get("messages")
            if not isinstance(messages, list):
                raise ValueError("unsupported messages format")

            for message in messages:
                if not isinstance(message, dict):
                    raise ValueError("unsupported message format")

                content = message.get("content")
                if not isinstance(content, str):
                    raise ValueError("unsupported content format")

                # 현재 L2는 도구 호출 내부 텍스트를 처리하지 않는다.
                if "tool_calls" in message or "function_call" in message:
                    raise ValueError("unsupported tool call format")

            if parsed.vendor == "anthropic" and body.get("system"):
                raise ValueError("system text is not supported yet")

        elif parsed.vendor == "gemini":
            if body.get("systemInstruction"):
                raise ValueError("system instruction is not supported yet")

            contents = body.get("contents")
            if not isinstance(contents, list):
                raise ValueError("unsupported contents format")

            for content in contents:
                if not isinstance(content, dict):
                    raise ValueError("unsupported content format")

                parts = content.get("parts")
                if not isinstance(parts, list):
                    raise ValueError("unsupported parts format")

                for part in parts:
                    if (
                        not isinstance(part, dict)
                        or set(part) != {"text"}
                        or not isinstance(part["text"], str)
                    ):
                        raise ValueError("unsupported part format")

        # 도구 정의 내 텍스트는 현재 탐지 범위에 포함되지 않는다.
        if body.get("tools") or body.get("functions"):
            raise ValueError("tool definitions are not supported yet")

    except Exception:
        context.status = "failed"
        context.error = "L2_PARSING_FAILED"
        return await audit_log_l9(context)

    # [L1 인가] 요청 모델의 사용 권한 확인
    if parsed.model not in user.allowed_models:
        context.status = "failed"
        context.error = "L1_MODEL_NOT_ALLOWED"
        return await audit_log_l9(context)

    # [L3] 전체 원문 기준 탐지
    try:
        l3_service = _get_l3_service()
        segment = parsed.segments[0]

        results = l3_service.analyze(
            raw_prompt=context.raw_prompt,
            segment_id=segment.segment_id,
        )

        # L3 결과는 이미 전체 원문 기준이므로 오프셋을 더하지 않는다.
        for det in results:
            context.detected_entities.append(_to_detected_pii(det, 0))

        context.validate_detected_spans()

    except Exception:
        context.status = "failed"
        context.error = "L3_DETECTION_FAILED"

    # [L4] 세그먼트 기준 탐지 후 전체 원문 위치로 변환
    if context.status == "success":
        try:
            offset = 0

            for seg in parsed.segments:
                l4_results: list[DetectedPII] = []

                l4_results.extend(
                    find_customer_id(
                        seg.text,
                        segment_id=seg.segment_id,
                    )
                )
                l4_results.extend(
                    find_customs_clearance_id(
                        seg.text,
                        segment_id=seg.segment_id,
                    )
                )
                l4_results.extend(
                    find_order_id(
                        seg.text,
                        segment_id=seg.segment_id,
                    )
                )
                l4_results.extend(
                    find_tracking_number(
                        seg.text,
                        segment_id=seg.segment_id,
                    )
                )

                for det in l4_results:
                    context.detected_entities.append(_to_detected_pii(det, offset))

                offset += len(seg.text) + 1

            context.validate_detected_spans()

        except Exception:
            context.status = "failed"
            context.error = "L4_DETECTION_FAILED"

    # [L5] 위험도 평가
    if context.status == "success":
        try:
            context = await run_l5_risk_scoring(context)

        except Exception:
            context.status = "failed"
            context.error = "L5_RISK_SCORING_FAILED"

    # [L6] 실제 가명화
    if context.status == "success":
        try:
            tokenizer = _get_l6_tokenizer()

            result = tokenizer.anonymize(
                session_id=context.session_id,
                raw_prompt=context.raw_prompt,
                detected_entities=context.detected_entities,
                policy_action=context.policy_action,
            )

            context.anonymized_prompt = result.anonymized_prompt
            context.vault_mapping = result.vault_mapping
            context.token_types = result.token_types

        except Exception:
            context.status = "failed"
            context.error = "L6_TOKENIZATION_FAILED"

    # [L2 재조립] 단일 세그먼트에 가명화 결과 반영
    if context.status == "success":
        try:
            if context.anonymized_prompt is None:
                raise ValueError("anonymized prompt is missing")

            seg = parsed.segments[0]

            processed_segments = [
                TextSegment(
                    segment_id=seg.segment_id,
                    path=seg.path,
                    role=seg.role,
                    text=context.anonymized_prompt,
                )
            ]

            context.reconstructed_body = adapter.rebuild(
                parsed,
                processed_segments,
            )

        except Exception:
            context.status = "failed"
            context.error = "L2_REBUILD_FAILED"

    # [L7] 가명화된 요청 중계
    if context.status == "success":
        try:
            context = await call_gemini_l7(context)

        except Exception:
            context.status = "failed"
            context.error = "L7_REQUEST_FAILED"

    # [L8] 응답 복원
    if context.status == "success":
        try:
            context = await restore_l8(context)

        except Exception:
            context.status = "failed"
            context.error = "L8_RESTORE_FAILED"

    # [L9] 실패 기록 또는 응답 스트림에 감사 로거 연결
    context = await audit_log_l9(context)

    return context
