"""설정 로딩 테스트."""

import pytest

from privacy_proxy.config import Settings


def test_secrets_are_not_exposed_in_repr() -> None:
    """비밀값이 repr에 평문으로 찍히면 로그·트레이스백으로 새어나간다."""
    settings = Settings(proxy_api_key="super-secret-value")

    assert "super-secret-value" not in repr(settings)
    assert settings.proxy_api_key.get_secret_value() == "super-secret-value"


def test_vault_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError):
        Settings(vault_ttl_seconds=0)
