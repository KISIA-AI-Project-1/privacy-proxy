"""Proxy-owned authentication, readiness and restoration regressions."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from privacy_proxy.adapters import get_current_user


@pytest.mark.asyncio
async def test_missing_proxy_key_is_not_example_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "privacy_proxy.adapters.get_settings", lambda: SimpleNamespace(proxy_api_key=SecretStr(""))
    )
    with pytest.raises(HTTPException) as error:
        await get_current_user("Bearer example-proxy-key")
    assert error.value.status_code == 401


def test_upload_removed() -> None:
    from privacy_proxy.main import app

    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/upload-log", params={"filename": "test", "content": "test"}
            ).status_code
            == 404
        )


def test_readiness_dependency_failure_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from privacy_proxy import main

    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(proxy_api_key=SecretStr("synthetic"))
    )
    monkeypatch.setattr(
        main, "_get_l3_service", Mock(side_effect=ValueError("SYNTHETIC_PRIVATE_ERROR"))
    )
    with TestClient(main.app) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert "SYNTHETIC_PRIVATE_ERROR" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
async def test_before_restore_capture(monkeypatch: pytest.MonkeyPatch, demo_mode: bool) -> None:
    from privacy_proxy.schemas import ProxyContext
    from restore.restorer import restore_l8

    monkeypatch.setattr(
        "restore.restorer.get_settings", lambda: SimpleNamespace(demo_mode=demo_mode)
    )

    async def chunks():
        yield "【PHO"
        yield "NE_1】"

    context = ProxyContext(
        vault_mapping={"【PHONE_1】": "010-9999-8888"}, llm_raw_response=chunks()
    )
    context = await restore_l8(context)
    restored = "".join([chunk async for chunk in context.final_response])
    assert restored == "010-9999-8888"
    assert context.upstream_response_text == ("【PHONE_1】" if demo_mode else "")
