"""Proxy wiring: existing L4/L5/L6, model-free L3 stub and external echo."""

from collections.abc import AsyncGenerator

import pytest

from privacy_proxy.pipeline import run_privacy_pipeline
from privacy_proxy.schemas import ProxyContext, UserContext
from tests.test_pipeline import PHONE, StubL3Service


@pytest.mark.parametrize(
    "text,value,kind",
    [
        ("환불 계좌번호 123456-01-234567입니다", "123456-01-234567", "ACCOUNT_NUMBER"),
        ("신한은행 계좌 110-123-456789", "110-123-456789", "ACCOUNT_NUMBER"),
        ("배송 주소는 101동 1203호", "101동 1203호", "ADDRESS_DETAIL"),
        ("테헤란로 123으로 배송", "테헤란로 123", "ADDRESS_ROAD"),
        ("저는 당뇨가 있어요", "당뇨", "SENSITIVE_HEALTH"),
    ],
)
@pytest.mark.asyncio
async def test_existing_l4_wiring(
    text: str, value: str, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Existing address GENERALIZE belongs to L6; exercise its TOKENIZE path.
    raw = f"연락처 {PHONE}. {text}"
    monkeypatch.setattr("privacy_proxy.pipeline._get_l3_service", lambda: StubL3Service())

    async def echo(context: ProxyContext) -> ProxyContext:
        outgoing = context.reconstructed_body["messages"][0]["content"]
        assert value not in outgoing
        assert PHONE not in outgoing

        async def stream() -> AsyncGenerator[str, None]:
            for start in range(0, len(outgoing), 3):
                yield outgoing[start : start + 3]

        context.llm_raw_response = stream()
        return context

    monkeypatch.setattr("privacy_proxy.pipeline.call_gemini_l7", echo)
    context = await run_privacy_pipeline(
        raw, UserContext(user_id="synthetic", role="developer", department="test")
    )
    assert context.status == "success", context.error
    assert kind in {str(entity.entity_type) for entity in context.detected_entities}
    assert context.final_response is not None
    assert "".join([chunk async for chunk in context.final_response]) == raw
    assert context.status == "success"


def test_anchor_coordinates_follow_nonzero_offset_base() -> None:
    from l4.recognizers import find_tracking_number

    from privacy_proxy.pipeline import _to_detected_pii

    segment = "송장번호: ABCD12345678 확인 부탁드려요"
    prefix = "안녕하세요 문의드립니다\n"
    [local] = find_tracking_number(segment)

    entity = _to_detected_pii(local, len(prefix))

    raw = prefix + segment
    assert entity.anchor_start is not None and entity.anchor_end is not None
    assert raw[entity.start_idx : entity.end_idx] == "ABCD12345678"
    assert raw[entity.anchor_start : entity.anchor_end] == "송장번호"
