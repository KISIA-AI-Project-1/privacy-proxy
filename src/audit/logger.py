import json
import logging
from datetime import UTC, datetime

from privacy_proxy.schemas import ProxyContext

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def audit_log_l9(context: ProxyContext) -> ProxyContext:
    """
    [L9 레이어]
    """
    # 1. 총 처리 시간 계산
    try:
        start_time = datetime.fromisoformat(context.created_at.replace("Z", "+00:00"))
        end_time = datetime.now(UTC)

        latency = (end_time - start_time).total_seconds() * 1000
        context.latency_ms["total_pipeline"] = round(latency, 2)
    except Exception as e:
        context.error = f"시간 계산 에러: {e!s}"
        context.latency_ms["total_pipeline"] = -1.0

    # 2. 민감 정보 및 거대 JSON 페이로드 제외를 통한 가독성 확보
    safe_log_data = context.model_dump(
        exclude_none=True, exclude={"parsed_request", "reconstructed_body"}
    )

    # 3. 터미널 로깅 및 상태 분기 출력
    separator = "=" * 50
    logger.info(f"\n{separator}")

    if context.status == "success":
        logger.info(
            f" [L9 Audit Log] Pipeline SUCCESS (Latency: {context.latency_ms.get('total_pipeline', 0)}ms)"
        )
    else:
        logger.info(" [L9 Audit Log] Pipeline FAILED")
        if context.error:
            logger.info(f"   [Error Details] {context.error}")

    logger.info(separator)
    logger.info(json.dumps(safe_log_data, indent=2, ensure_ascii=False))
    logger.info(f"{separator}\n")

    return context
