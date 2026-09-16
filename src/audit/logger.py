import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from privacy_proxy.schemas import ProxyContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def audit_log_l9(context: ProxyContext) -> ProxyContext:
    """
    [L9 레이어: 비동기 스트리밍 로거]
    """
    if context.status == "failed" or not hasattr(context, "final_response") or not context.final_response:
        _print_log(context)
        return context

    async def _logging_stream_wrapper(original_stream: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        full_response_text = ""
        first_token_time = None

        try:
            async for chunk in original_stream:
                if first_token_time is None:
                    first_token_time = datetime.now(UTC)

                full_response_text += chunk
                yield chunk

        finally:
            end_time = datetime.now(UTC)
            start_time = datetime.fromisoformat(context.created_at.replace("Z", "+00:00"))

            if first_token_time:
                context.latency_ms["ttft"] = round((first_token_time - start_time).total_seconds() * 1000, 2)
            context.latency_ms["total_pipeline"] = round((end_time - start_time).total_seconds() * 1000, 2)

            context.final_response_log = full_response_text

            _print_log(context)


    context.final_response = _logging_stream_wrapper(context.final_response)

    return context


def _print_log(context: ProxyContext) -> None:
    """
    [추가] 실제 터미널에 JSON 포맷으로 로그를 찍는 분리된 함수
    """
    safe_log_data = context.model_dump(
        exclude_none=True,
        exclude={"parsed_request", "reconstructed_body", "llm_raw_response", "final_response"}
    )

    if hasattr(context, "final_response_log"):
        safe_log_data["final_response"] = context.final_response_log

    separator = "=" * 50
    logger.info(f"\n{separator}")

    if context.status == "success":
        ttft = context.latency_ms.get('ttft', 0)
        total = context.latency_ms.get('total_pipeline', 0)
        logger.info(f" [L9 Audit Log] Pipeline SUCCESS (TTFT: {ttft}ms, Total: {total}ms)")
    else:
        logger.info(" [L9 Audit Log] Pipeline FAILED")
        if context.error:
            logger.info(f"   [Error Details] {context.error}")

    logger.info(separator)
    logger.info(json.dumps(safe_log_data, indent=2, ensure_ascii=False))
    logger.info(f"{separator}\n")
