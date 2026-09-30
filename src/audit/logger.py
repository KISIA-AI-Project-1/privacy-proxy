import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from privacy_proxy.schemas import ProxyContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_SAFE_ERROR_CODES = frozenset(
    {
        "L2_PARSING_FAILED",
        "L2_REBUILD_FAILED",
        "L3_DETECTION_FAILED",
        "L4_DETECTION_FAILED",
        "L5_VALIDATION_FAILED",
        "L5_RISK_ASSESSMENT_FAILED",
        "L6_TOKENIZATION_FAILED",
        "L7_REQUEST_FAILED",
        "L8_RESTORE_FAILED",
    }
)


async def audit_log_l9(context: ProxyContext) -> ProxyContext:
    """
    [L9 레이어: 비동기 스트리밍 로거]
    """
    if (
        context.status == "failed"
        or not hasattr(context, "final_response")
        or not context.final_response
    ):
        _print_log(context)
        return context

    async def _logging_stream_wrapper(
        original_stream: AsyncGenerator[str, None],
    ) -> AsyncGenerator[str, None]:
        first_token_time = None

        try:
            async for chunk in original_stream:
                if first_token_time is None:
                    first_token_time = datetime.now(UTC)

                yield chunk

        finally:
            end_time = datetime.now(UTC)
            start_time = datetime.fromisoformat(context.created_at.replace("Z", "+00:00"))

            if first_token_time:
                context.latency_ms["ttft"] = round(
                    (first_token_time - start_time).total_seconds() * 1000, 2
                )
            context.latency_ms["total_pipeline"] = round(
                (end_time - start_time).total_seconds() * 1000, 2
            )

            _print_log(context)

    context.final_response = _logging_stream_wrapper(context.final_response)

    return context


def _print_log(context: ProxyContext) -> None:
    """Log operational metadata from an explicit allowlist.

    The full context contains raw detections, token mappings, reconstructed
    request bodies, and restored model output. None of those fields belong in
    an audit event.
    """
    error_code = context.error
    if error_code is not None and error_code not in _SAFE_ERROR_CODES:
        error_code = "UNCLASSIFIED_FAILURE"
    safe_log_data = {
        "session_id": context.session_id,
        "created_at": context.created_at,
        "status": context.status,
        "error_code": error_code,
        "risk_score": context.risk_score,
        "risk_level": context.risk_level,
        "policy_action": context.policy_action,
        "latency_ms": context.latency_ms,
    }

    separator = "=" * 50
    logger.info(f"\n{separator}")

    if context.status == "success":
        ttft = context.latency_ms.get("ttft", 0)
        total = context.latency_ms.get("total_pipeline", 0)
        logger.info(f" [L9 Audit Log] Pipeline SUCCESS (TTFT: {ttft}ms, Total: {total}ms)")
    else:
        logger.info(" [L9 Audit Log] Pipeline FAILED")
        if error_code:
            logger.info("   [Error Code] %s", error_code)

    logger.info(separator)
    logger.info(json.dumps(safe_log_data, indent=2, ensure_ascii=False))
    logger.info(f"{separator}\n")
