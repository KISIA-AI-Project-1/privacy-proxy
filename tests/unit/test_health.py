"""부팅 스모크 테스트. 파이프라인 계층별 테스트는 각 담당자가 추가한다."""

from fastapi.testclient import TestClient

from privacy_proxy.main import app


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
