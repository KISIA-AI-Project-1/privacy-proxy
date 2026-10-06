import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterable
from datetime import UTC, datetime
from typing import cast

from privacy_proxy.schemas import ProxyContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_SAFE_ERROR_CODES = frozenset(
    {
        "L2_PARSING_FAILED",
        "L2_REBUILD_FAILED",
        "MULTI_SEGMENT_NOT_SUPPORTED",
        "L3_DETECTION_FAILED",
        "L4_DETECTION_FAILED",
        "DETECTION_FAILED",
        "L5_VALIDATION_FAILED",
        "L5_RISK_ASSESSMENT_FAILED",
        "L5_RISK_SCORING_FAILED",
        "L6_TOKENIZATION_FAILED",
        "L7_REQUEST_FAILED",
        "L7_PARSED_REQUEST_MISSING",
        "L7_RECONSTRUCTED_BODY_MISSING",
        "L7_UNSUPPORTED_VENDOR",
        "L7_API_KEY_MISSING",
        "L7_STREAM_FAILED",
        "L8_RESTORE_FAILED",
        "L8_INVALID_MAPPING",
        "L8_STREAM_FAILED",
        "RESPONSE_STREAM_FAILED",
        "RESPONSE_STREAM_CANCELLED",
        "FINAL_RESPONSE_MISSING",
    }
)


async def audit_log_l9(context: ProxyContext) -> ProxyContext:
    """L9: 응답 스트림이 종료된 후 감사 로그를 기록한다."""
    if context.status != "success" or context.final_response is None:
        _print_log(context)
        return context

    async def _logging_stream_wrapper(
        original_stream: AsyncIterable[str],
    ) -> AsyncGenerator[str, None]:
        first_token_time: datetime | None = None

        try:
            async for chunk in original_stream:
                if chunk and first_token_time is None:
                    first_token_time = datetime.now(UTC)

                yield chunk

        except (asyncio.CancelledError, GeneratorExit):
            if context.status == "success":
                context.status = "failed"
                context.error = "RESPONSE_STREAM_CANCELLED"
            raise

        except Exception:
            # L7·L8에서 이미 기록한 오류는 유지한다.
            if context.status == "success":
                context.status = "failed"
                context.error = "RESPONSE_STREAM_FAILED"
            raise

        finally:
            end_time = datetime.now(UTC)
            start_time = datetime.fromisoformat(context.created_at.replace("Z", "+00:00"))

            if first_token_time is not None:
                context.latency_ms["ttft"] = round(
                    (first_token_time - start_time).total_seconds() * 1000,
                    2,
                )

            context.latency_ms["total_pipeline"] = round(
                (end_time - start_time).total_seconds() * 1000,
                2,
            )

            _print_log(context)

    original_stream = cast(
        AsyncIterable[str],
        context.final_response,
    )
    context.final_response = _logging_stream_wrapper(original_stream)

    return context


def _print_log(context: ProxyContext) -> None:
    """허용한 운영 메타데이터만 감사 로그에 기록한다.

    원문, 탐지 값, 복원 매핑, 재조립 요청과 복원 응답은
    감사 로그에 포함하지 않는다.
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
    logger.info("\n%s", separator)

    if context.status == "success":
        ttft = context.latency_ms.get("ttft", 0)
        total = context.latency_ms.get("total_pipeline", 0)

        logger.info(
            " [L9 Audit Log] Pipeline SUCCESS (TTFT: %sms, Total: %sms)",
            ttft,
            total,
        )
    else:
        logger.info(" [L9 Audit Log] Pipeline FAILED")
        if error_code:
            logger.info("   [Error Code] %s", error_code)

    logger.info("%s", separator)
    logger.info(
        "%s",
        json.dumps(safe_log_data, indent=2, ensure_ascii=False),
    )
    logger.info("%s\n", separator)
