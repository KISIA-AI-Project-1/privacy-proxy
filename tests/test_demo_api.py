from collections.abc import AsyncGenerator, Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from privacy_proxy.adapters import get_current_user
from privacy_proxy.risk.score import assess_risk
from privacy_proxy.schemas import (
    DetectedPII,
    DetectionTier,
    EntityOutcome,
    ParsedRequest,
    ProxyContext,
    UserContext,
)


@pytest.fixture
def demo_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, AsyncMock]]:
    """외부 AWS·LLM 호출 없이 시연 API를 검사한다."""
    with patch("boto3.client"):
        from privacy_proxy import main

    # 기본은 시연 모드 활성화. 개별 테스트에서 변경할 수 있다.
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=True),
    )

    pipeline = AsyncMock()
    monkeypatch.setattr(main, "run_privacy_pipeline", pipeline)

    original_overrides = dict(main.app.dependency_overrides)
    main.app.dependency_overrides.clear()

    try:
        with TestClient(main.app) as client:
            yield client, pipeline
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(original_overrides)


def test_demo_disabled(
    demo_client: tuple[TestClient, AsyncMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """시연 모드가 꺼져 있으면 파이프라인을 실행하지 않는다."""
    from privacy_proxy import main

    client, pipeline = demo_client

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(demo_mode=False),
    )

    response = client.post("/v1/demo/chat", json={})

    assert response.status_code == 404
    pipeline.assert_not_awaited()


def test_demo_requires_authentication(
    demo_client: tuple[TestClient, AsyncMock],
) -> None:
    """시연 모드에서도 인증 없이 사용할 수 없다."""
    client, pipeline = demo_client

    response = client.post("/v1/demo/chat", json={})

    assert response.status_code == 401
    pipeline.assert_not_awaited()


def test_demo_returns_stage_results(
    demo_client: tuple[TestClient, AsyncMock],
) -> None:
    """시연 화면용 데이터와 최종 응답을 반환한다."""
    from privacy_proxy import main

    client, pipeline = demo_client

    user = UserContext(
        user_id="demo-test-user",
        department="Dev",
        role="developer",
    )
    main.app.dependency_overrides[get_current_user] = lambda: user

    original = "010-9999-8888"
    placeholder = "【PHONE_1】"

    async def restored_stream() -> AsyncGenerator[str, None]:
        yield "연락처: "
        yield original

    context = ProxyContext(
        raw_prompt=original,
        parsed_request=ParsedRequest(
            vendor="openai",
            model="gpt-4o-mini",
            segments=[],
            original_body={},
        ),
        detected_entities=[
            DetectedPII(
                segment_id="seg-1",
                start_idx=0,
                end_idx=len(original),
                entity_type="PHONE_NUMBER",
                confidence=None,
                source="TEST",
                tier=DetectionTier.RULE_ANCHORED,
                original_value=original,
                normalized=original,
            )
        ],
        risk_score=80.0,
        risk_level="HIGH",
        risk_reasons=["테스트 판단 이유"],
        policy_action="TOKENIZE",
        anonymized_prompt=placeholder,
        vault_mapping={placeholder: original},
        token_types={placeholder: "PHONE_NUMBER"},
        upstream_request_body={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": placeholder}],
            "stream": True,
        },
        final_response=restored_stream(),
    )
    assess_risk(context)

    context.entity_outcomes = [
        EntityOutcome(
            segment_id="seg-1",
            start_idx=0,
            end_idx=len(original),
            entity_type="PHONE_NUMBER",
            action="TOKENIZE",
        )
    ]

    pipeline.return_value = context

    body = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": original}],
    }
    response = client.post("/v1/demo/chat", json=body)

    assert response.status_code == 200
    data = response.json()

    assert data["input"]["text"] == original
    assert data["detection"]["count"] == 1
    assert data["detection"]["entities"][0]["entity_type"] == "PHONE_NUMBER"
    assert data["risk"]["score"] == 80.0
    assert data["risk"]["policy_action"] == "TOKENIZE"
    assert data["risk"]["entity_policies"] == [
        {
            "segment_id": "seg-1",
            "start_idx": 0,
            "end_idx": len(original),
            "entity_type": "PHONE_NUMBER",
            "privacy_class": "DIRECT_IDENTIFIER",
            "action": "TOKENIZE",
            "reason": "직접식별자: 가역 토큰화",
            "applied": "TOKENIZE",
        }
    ]
    assert data["anonymization"]["text"] == placeholder
    assert data["anonymization"]["entity_outcomes"] == [
        outcome.model_dump() for outcome in context.entity_outcomes
    ]
    assert data["upstream"]["request_body"] == context.upstream_request_body
    assert data["response"]["text"] == f"연락처: {original}"

    # 복원 매핑 전체와 인증 헤더는 반환하지 않는다.
    assert "vault_mapping" not in data
    assert "headers" not in data["upstream"]

    pipeline.assert_awaited_once_with(body=body, user=user)
