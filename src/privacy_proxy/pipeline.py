from typing import Any

from l4.recognizers import (
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)

from audit.logger import audit_log_l9
from privacy_proxy.adapters import AdapterRouter
from privacy_proxy.l4_adapter import translate_segment_detection
from privacy_proxy.risk import run_l5_risk_scoring
from privacy_proxy.schemas import (
    DetectedPII,
    DetectionTier,
    ProxyContext,
    TextSegment,
    UserContext,
)
from restore.restorer import restore_l8
from upstream.llm_client import call_gemini_l7

from .mock_layers import mock_l6_vault_tokenization

# ── [바뀐 점 1] L3 서비스를 맨 위에서 import하지 않고, 처음 쓸 때 불러오는 함수 ──
_l3_service = None


def _get_l3_service():
    global _l3_service
    if _l3_service is None:
        from privacy_proxy.l3.service import L3AnalyzerService

        _l3_service = L3AnalyzerService()
    return _l3_service


def _to_detected_pii(det, offset_base: int) -> DetectedPII:
    """L3/L4가 돌려준 결과를 공통 형식(DetectedPII)으로 바꾸고,
    세그먼트 기준 위치를 raw_prompt 기준 위치로 옮긴다."""
    if isinstance(det, DetectedPII):
        return translate_segment_detection(det, offset_base=offset_base)

    # contracts.Detection(dataclass)인 경우: 필드를 하나씩 옮겨 담는다
    return DetectedPII(
        segment_id=det.segment_id,
        start_idx=det.start_idx + offset_base,
        end_idx=det.end_idx + offset_base,
        entity_type=det.entity_type,
        confidence=det.confidence,
        source=det.source,
        tier=DetectionTier(det.tier) if det.tier else DetectionTier.CANDIDATE,
        original_value=det.original_value,
        normalized=det.normalized,
    )


async def run_privacy_pipeline(body: dict[str, Any], user: UserContext) -> ProxyContext:
    if user is None:
        user = UserContext(user_id="test_user", role="user", department="Dev")

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
        return context

    # ── [바뀐 점 2] 세그먼트가 2개 이상이면 실패 (L6 붙일 때 이 부분을 지우고 구현) ──
    if len(parsed.segments) > 1:
        context.status = "failed"
        context.error = "MULTI_SEGMENT_NOT_SUPPORTED"
        return context

    # ── [바뀐 점 3] L3 + L4 탐지 (detected_pii → detected_entities, 오프셋 누적) ──
    try:
        l3_service = _get_l3_service()
        offset = 0
        for seg in parsed.segments:
            for det in l3_service.analyze(raw_prompt=seg.text, segment_id=seg.segment_id):
                context.detected_entities.append(_to_detected_pii(det, offset))  # ← L3

            l4_results = []
            l4_results.extend(find_customer_id(seg.text))
            l4_results.extend(find_customs_clearance_id(seg.text))
            l4_results.extend(find_order_id(seg.text))
            l4_results.extend(find_tracking_number(seg.text))
            for det in l4_results:
                context.detected_entities.append(_to_detected_pii(det, offset))  # ← L4

            offset += len(seg.text) + 1

        context.validate_detected_spans()
    except Exception as e:
        import traceback

        traceback.print_exc()
        context.status = "failed"
        context.error = f"DETECTION_FAILED: {type(e).__name__}: {e}"

    # [L5] 위험도
    if context.status == "success":
        try:
            context = await run_l5_risk_scoring(context)
        except Exception as e:
            context.status = "failed"
            context.error = f"L5_RISK_SCORING_FAILED: {e}"

    # [L6] 가명화 (아직 mock)
    if context.status == "success":
        context = await mock_l6_vault_tokenization(context)

    # [L2 재조립] (L6 붙일 때 수정 예정)
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
            context.error = f"L2_REBUILD_FAILED: {e}"
            return context

    # [L7 ~ L9]
    if context.status == "success":
        context = await call_gemini_l7(context)

    if context.status == "success":
        context = await restore_l8(context)

    context = await audit_log_l9(context)

    return context
