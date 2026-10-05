from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from privacy_proxy.pipeline import run_privacy_pipeline
from privacy_proxy.schemas import (
    DetectedPII,
    DetectionTier,
    ProxyContext,
    UserContext,
)

PHONE = "010-9999-8888"
ORDER = "20261003-123456"


class StubL3Service:
    """무거운 L3 초기화 대신 정해진 전화번호 결과를 반환한다."""

    def analyze(
        self,
        raw_prompt: str,
        segment_id: str,
    ) -> list[DetectedPII]:
        if PHONE not in raw_prompt:
            return []

        start = raw_prompt.index(PHONE)

        return [
            DetectedPII(
                segment_id=segment_id,
                start_idx=start,
                end_idx=start + len(PHONE),
                entity_type="PHONE_NUMBER",
                confidence=None,
                source="TEST_L3",
                tier=DetectionTier.RULE_ANCHORED,
                original_value=PHONE,
                normalized=PHONE,
            )
        ]


def test_healthz() -> None:
    """외부 AWS 호출 없이 헬스체크를 검증한다."""
    # main.py의 전역 S3 클라이언트 생성을 테스트에서 대체한다.
    with patch("boto3.client"):
        from privacy_proxy.main import app

        with TestClient(app) as client:
            response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_full_pipeline_success() -> None:
    """가명화된 요청과 스트림 복원·감사 기록까지 검증한다."""
    original_text = f"연락처: {PHONE}. 주문번호: {ORDER}."

    raw_input = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": original_text,
            }
        ],
    }
    mock_user = UserContext(
        user_id="test-user",
        role="user",
        department="Dev",
    )

    async def mock_call_llm(context: ProxyContext) -> ProxyContext:
        anonymized_text = context.anonymized_prompt
        assert anonymized_text is not None

        # L7에 전달되는 요청에는 원문 개인정보가 없어야 한다.
        assert PHONE not in anonymized_text
        assert ORDER not in anonymized_text
        assert context.reconstructed_body["messages"][0]["content"] == anonymized_text
        assert set(context.token_types.values()) == {
            "PHONE_NUMBER",
            "ORDER_ID",
        }

        async def mock_stream() -> AsyncGenerator[str, None]:
            yield "응답: "

            # 토큰이 청크 경계에서 잘려도 복원되어야 한다.
            for character in anonymized_text:
                yield character

            yield " (테스트 완료)"

        context.llm_raw_response = mock_stream()
        return context

    with (
        patch(
            "privacy_proxy.pipeline._get_l3_service",
            return_value=StubL3Service(),
        ),
        patch(
            "privacy_proxy.pipeline.call_gemini_l7",
            new=mock_call_llm,
        ),
    ):
        context = await run_privacy_pipeline(
            raw_input,
            user=mock_user,
        )

        assert context.status == "success", context.error
        assert context.error is None
        assert context.policy_action == "TOKENIZE"
        assert context.vault_mapping
        assert context.final_response is not None

        # 스트림을 읽어야 L8 복원과 L9 완료 기록이 실행된다.
        chunks: list[str] = []
        async for chunk in context.final_response:
            chunks.append(chunk)

    restored_text = "".join(chunks)

    assert restored_text == f"응답: {original_text} (테스트 완료)"
    assert context.status == "success"
    assert context.error is None
    assert "total_pipeline" in context.latency_ms


@pytest.mark.asyncio
async def test_pipeline_with_empty_input() -> None:
    """빈 입력은 실패 처리하고 L6·L7을 실행하지 않는다."""
    mock_user = UserContext(
        user_id="test-user",
        role="user",
        department="Dev",
    )

    l6_factory = Mock()
    l7 = AsyncMock()

    with (
        patch(
            "privacy_proxy.pipeline._get_l6_tokenizer",
            l6_factory,
        ),
        patch(
            "privacy_proxy.pipeline.call_gemini_l7",
            l7,
        ),
    ):
        context = await run_privacy_pipeline(
            "",
            user=mock_user,
        )

    assert context.status == "failed"
    assert context.error == "L2_PARSING_FAILED"
    l6_factory.assert_not_called()
    l7.assert_not_awaited()


@pytest.mark.asyncio
async def test_l5_failure_prevents_l6_and_l7_calls() -> None:
    """L5가 거절한 요청은 가명화와 외부 전송을 진행하지 않는다."""
    private_value = "private-person@example.com"

    raw_input = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": private_value,
            }
        ],
    }
    mock_user = UserContext(
        user_id="test-user",
        role="user",
        department="Dev",
    )

    # L4가 L5에서 지원하지 않는 엔티티를 반환하는 상황을 만든다.
    unsupported_entity = DetectedPII(
        segment_id="seg-1",
        entity_type="UNSUPPORTED_PRIVATE_TYPE",
        original_value=private_value,
        start_idx=0,
        end_idx=len(private_value),
        confidence=1.0,
        tier=DetectionTier.MODEL,
        source="INTEGRATION_TEST",
        normalized=private_value,
    )

    l6_factory = Mock()
    l7 = AsyncMock()

    with (
        patch(
            "privacy_proxy.pipeline._get_l3_service",
            return_value=StubL3Service(),
        ),
        patch(
            "privacy_proxy.pipeline.find_customer_id",
            return_value=[unsupported_entity],
        ),
        patch(
            "privacy_proxy.pipeline._get_l6_tokenizer",
            l6_factory,
        ),
        patch(
            "privacy_proxy.pipeline.call_gemini_l7",
            l7,
        ),
    ):
        context = await run_privacy_pipeline(
            raw_input,
            user=mock_user,
        )

    assert context.status == "failed"
    assert context.error == "L5_VALIDATION_FAILED"
    assert private_value not in context.error
    l6_factory.assert_not_called()
    l7.assert_not_awaited()
