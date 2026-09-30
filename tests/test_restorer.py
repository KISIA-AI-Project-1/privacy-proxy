from collections.abc import AsyncGenerator

import pytest

from privacy_proxy.schemas import ProxyContext
from restore.restorer import restore_l8


async def mock_l7_stream(text: str) -> AsyncGenerator[str, None]:
    for chunk in [text[i : i + 3] for i in range(0, len(text), 3)]:
        yield chunk


@pytest.mark.asyncio
async def test_restore_l8_success() -> None:
    """합성 번호(010-1111-1111)가 실제 원본 번호로 정확히 역치환되는지 검증"""
    fake_phone = "010-1111-1111"
    real_phone = "010-1234-1234"

    context = ProxyContext(
        raw_prompt=f"제 번호는 {real_phone}입니다.",
        anonymized_prompt=f"제 번호는 {fake_phone}입니다.",
        llm_raw_response=mock_l7_stream(f"알겠습니다. {fake_phone} 번호로 연락드리겠습니다."),
        vault_mapping={fake_phone: real_phone},
    )
    context.status = "success"

    result_context = await restore_l8(context)

    assert result_context.status == "success"
    assert result_context.final_response is not None

    # 스트림 소비 후 결합
    restored_text = ""
    async for chunk in result_context.final_response:
        restored_text += chunk

    # 가짜 번호는 사라지고 진짜 번호로 복원되었는지 확인
    assert fake_phone not in restored_text
    assert real_phone in restored_text
    assert restored_text == f"알겠습니다. {real_phone} 번호로 연락드리겠습니다."
