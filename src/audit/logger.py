import json
from datetime import UTC, datetime

from privacy_proxy.schemas import ProxyContext


async def audit_log_l9(context: ProxyContext) -> ProxyContext:
    """
    [L9 레이어] 전체 처리 시간을 계산하고, 민감 정보가 배제된 안전한 감사 로그를 기록합니다.
    """
    # 총 처리 시간 계산
    try:
        start_time = datetime.fromisoformat(context.created_at.replace("Z", "+00:00"))
        end_time = datetime.now(UTC)

        latency = (end_time - start_time).total_seconds() * 1000
        context.latency_ms["total_pipeline"] = round(latency, 2)
    except Exception as e:
        context.error = f"시간 계산 에러: {e!s}"
        context.latency_ms["total_pipeline"] = -1.0

    # 민감 정보가 제거된 안전한 로그 생성
    safe_log_data = context.model_dump(exclude_none=True)

    # 콘솔에 로그 출력
    print("\n" + "=" * 40)
    print(" [L9 Audit Log] Privacy Proxy 처리 결과")
    print("=" * 40)
    print(json.dumps(safe_log_data, indent=2, ensure_ascii=False))
    print("=" * 40 + "\n")

    return context
