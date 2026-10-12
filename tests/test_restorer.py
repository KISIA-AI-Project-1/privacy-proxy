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


# These tests exercise the existing L8 algorithm; no restoration policy is invented.
ALIASES = (
    ("health_hint", "【HEALTH_1:건강정보】", "가상 건강 상태"),
    ("product", "【PRODUCT_1】", "가상 상품"),
    ("name_1", "홍길동", "김가상"),
    ("name_2", "성춘향", "이가상"),
)

BOUNDARIES = [
    pytest.param(alias, original, split, id=f"{name}-split-{split}")
    for name, alias, original in ALIASES
    for split in range(len(alias) + 1)
]


async def restore_chunks(parts: list[str], mapping: dict[str, str]) -> str:
    async def source() -> AsyncGenerator[str, None]:
        for part in parts:
            yield part

    context = ProxyContext(vault_mapping=mapping, llm_raw_response=source())
    await restore_l8(context)
    assert context.final_response is not None
    output = "".join([part async for part in context.final_response])
    assert context.status == "success"
    return output


@pytest.mark.asyncio
@pytest.mark.parametrize("alias,original,split", BOUNDARIES)
async def test_every_alias_boundary(alias: str, original: str, split: int) -> None:
    parts = ["응답: " + alias[:split], alias[split:] + " 완료"]
    assert await restore_chunks(parts, {alias: original}) == f"응답: {original} 완료"


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [1, 2, 3, 5])
async def test_mixed_tokens_names_and_irreversible_address(width: int) -> None:
    text = "홍길동: 【HEALTH_1:건강정보】, 【PRODUCT_1】, 정기배송, 【ADDRESS】. 홍길동"
    mapping = {
        "홍길동": "김가상",
        "【HEALTH_1:건강정보】": "가상 건강 상태",
        "【PRODUCT_1】": "가상 상품",
    }
    parts = [text[start : start + width] for start in range(0, len(text), width)]
    expected = "김가상: 가상 건강 상태, 가상 상품, 정기배송, 【ADDRESS】. 김가상"
    assert await restore_chunks(parts, mapping) == expected


@pytest.mark.asyncio
async def test_no_mapping_keeps_purchase_and_generalized_address() -> None:
    assert (
        await restore_chunks(["매달 정기", "배송. 【ADD", "RESS】"], {})
        == "매달 정기배송. 【ADDRESS】"
    )


@pytest.mark.asyncio
async def test_token_number_prefixes_do_not_collide() -> None:
    text = "【PRODUCT_1】 / 【PRODUCT_10】"
    parts = list(text)
    mapping = {"【PRODUCT_1】": "첫 상품", "【PRODUCT_10】": "열 번째 상품"}
    assert await restore_chunks(parts, mapping) == "첫 상품 / 열 번째 상품"
