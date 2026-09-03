from audit.logger import audit_log_l9
from privacy_proxy.schemas import ProxyContext
from restore.restorer import restore_l8
from upstream.llm_client import call_gemini_l7

from .mock_layers import (
    mock_l3_detection,
    mock_l4_detection_ecommerce,
    mock_l5_risk_scoring,
    mock_l6_vault_tokenization,
)


async def run_privacy_pipeline(raw_text: str) -> ProxyContext:
    """
    [L1~L9 통합 오케스트레이션]
    입력된 텍스트를 각 레이어에 순서대로 통과시킵니다.
    """

    context = ProxyContext(raw_prompt=raw_text)

    if context.status == "success":
        context = await mock_l3_detection(context)

    if context.status == "success":
        context = await mock_l4_detection_ecommerce(context)

    if context.status == "success":
        context = await mock_l5_risk_scoring(context)

    if context.status == "success":
        context = await mock_l6_vault_tokenization(context)

    if context.status == "success":
        context = await call_gemini_l7(context)

    if context.status == "success":
        context = await restore_l8(context)

    context = await audit_log_l9(context)

    return context
