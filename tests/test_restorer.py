import pytest

from privacy_proxy.schemas import ProxyContext
from restore.restorer import restore_l8


@pytest.mark.asyncio
async def test_restore_l8_success() -> None:
    """금고에 맵핑된 토큰이 실제 원본 값으로 완벽히 치환되는지 검증"""
    context = ProxyContext(
        raw_prompt="제 번호는 <PHONE_1>입니다.",
        anonymized_prompt="제 번호는 <PHONE_1>입니다.",
        llm_raw_response="알겠습니다. <PHONE_1> 번호로 연락드리겠습니다.",
        vault_mapping={"<PHONE_1>": "010-1234-5678"},
    )
    context.status = "success"

    # L8 역치환 실행
    result_context = await restore_l8(context)

    # 토큰이 원본 번호로 완전히 바뀌었는지 확인
    assert result_context.status == "success"
    assert result_context.final_response is not None
    assert "<PHONE_1>" not in result_context.final_response
    assert "010-1234-5678" in result_context.final_response


@pytest.mark.asyncio
async def test_restore_l8_failed_status() -> None:
    """이전 단계에서 이미 실패한 컨텍스트가 들어오면 L8이 스킵되는지 검증"""
    context = ProxyContext(raw_prompt="테스트")
    context.status = "failed"
    context.llm_raw_response = "응답 내용"

    result_context = await restore_l8(context)

    # 실패 상태가 유지되고 에러 없이 그대로 반환되는지 확인
    assert result_context.status == "failed"
    assert result_context.final_response is None
