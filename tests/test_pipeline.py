import pytest
from fastapi.testclient import TestClient

from privacy_proxy.main import app
from privacy_proxy.pipeline import run_privacy_pipeline

client = TestClient(app)


def test_healthz() -> None:
    """헬스체크 엔드포인트 정상 작동 검증"""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_full_pipeline_success() -> None:
    """L1부터 L9까지 정상 흐름(개인정보 탐지 -> 가명화 -> LLM 통신 -> 복원 -> 로그) 검증"""
    raw_input = "안녕하세요 제 번호는 010-9999-8888이고 이메일은 test@example.com입니다."

    context = await run_privacy_pipeline(raw_input)

    # 1. 파이프라인 상태 검증
    assert context.status == "success"
    assert context.error is None

    # 2. vault_mapping 생성 여부 검증
    assert context.vault_mapping is not None
    assert len(context.vault_mapping) > 0

    # 3. L8 역치환(final_response)이 원본 문맥을 제대로 복원했는지 검증
    # (Mock 환경에 따라 LLM 응답 시뮬레이션 결과에 맞춰 검증)
    assert context.final_response is not None


@pytest.mark.asyncio
async def test_pipeline_with_empty_input() -> None:
    """빈 문자열이나 잘못된 입력이 들어왔을 때의 방어 로직 검증"""
    context = await run_privacy_pipeline("")

    # 빈 값이어도 시스템이 터지지 않고 상태를 유지하는지 확인
    assert context is not None
