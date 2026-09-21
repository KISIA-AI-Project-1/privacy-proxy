from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from privacy_proxy.main import app
from privacy_proxy.pipeline import run_privacy_pipeline
from privacy_proxy.schemas import ProxyContext, UserContext

client = TestClient(app)


def test_healthz() -> None:
    """헬스체크 엔드포인트 정상 작동 검증"""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_full_pipeline_success() -> None:
    """L1부터 L9까지 정상 흐름(개인정보 탐지 -> 가명화 -> LLM 통신 -> 복원 -> 로그) 검증"""
    raw_input = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": "안녕하세요 제 번호는 010-9999-8888이고 이메일은 test@example.com입니다.",
            }
        ],
    }
    mock_user = UserContext(user_id="test-user", role="user", department="Dev")

    # 1. 구글 서버 대신 일해줄 가짜 함수 정의
    async def mock_call_llm(context: ProxyContext) -> ProxyContext:
        async def mock_stream() -> AsyncGenerator[str, None]:
            yield "응답: "
            yield context.anonymized_prompt or ""
            yield " (테스트 완료)"

        context.llm_raw_response = mock_stream()
        return context

    # 2. call_gemini_l7을 가짜 함수로 가로채기(patch)한 상태에서 파이프라인 실행
    with patch("privacy_proxy.pipeline.call_gemini_l7", side_effect=mock_call_llm):
        context = await run_privacy_pipeline(raw_input, user=mock_user)

    # 에러출력
    if context.status != "success":
        print(f"\n[CI 에러 원인 확인] error: {context.error}\n")

    # 3. 파이프라인 상태 검증
    assert context.status == "success"
    assert context.error is None
    assert context.vault_mapping is not None
    assert len(context.vault_mapping) > 0
    assert context.final_response is not None


@pytest.mark.asyncio
async def test_pipeline_with_empty_input() -> None:
    """빈 문자열이나 잘못된 입력이 들어왔을 때의 방어 로직 검증"""
    mock_user = UserContext(user_id="test-user", role="user", department="Dev")
    context = await run_privacy_pipeline("", user=mock_user)

    # 빈 값이어도 시스템이 터지지 않고 상태를 유지하는지 확인
    assert context is not None
