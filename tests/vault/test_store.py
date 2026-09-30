import time

import redis
from cryptography.fernet import Fernet

from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import SessionVault


def create_vault(ttl: int = 1800) -> SessionVault:
    client = redis.Redis(host="localhost", port=6379)

    key = Fernet.generate_key().decode()
    crypto = VaultCrypto(key)

    return SessionVault(
        redis_client=client,
        crypto=crypto,
        ttl=ttl,
    )


def test_save_and_get_mapping():
    vault = create_vault()

    vault.save_mapping(
        session_id="crypto-store-test",
        entity_type="PERSON",
        original="김민수",
        token="[PERSON_1]",
    )

    result = vault.get_token(
        session_id="crypto-store-test",
        entity_type="PERSON",
        original="김민수",
    )

    assert result == "[PERSON_1]"


def test_delete_mapping():
    vault = create_vault()

    vault.save_mapping(
        session_id="delete-test",
        entity_type="PERSON",
        original="김민수",
        token="[PERSON_1]",
    )

    vault.delete_mapping(
        session_id="delete-test",
        entity_type="PERSON",
        original="김민수",
    )

    result = vault.get_token(
        session_id="delete-test",
        entity_type="PERSON",
        original="김민수",
    )

    assert result is None


def test_session_is_separated():
    vault = create_vault()

    vault.save_mapping(
        session_id="session-a",
        entity_type="PERSON",
        original="김민수",
        token="[PERSON_1]",
    )

    result = vault.get_token(
        session_id="session-b",
        entity_type="PERSON",
        original="김민수",
    )

    assert result is None


def test_mapping_expires_after_ttl():
    vault = create_vault(ttl=1)

    vault.save_mapping(
        session_id="ttl-test",
        entity_type="PERSON",
        original="김민수",
        token="[PERSON_1]",
    )

    # 저장 직후에는 조회 가능
    result_before_expire = vault.get_token(
        session_id="ttl-test",
        entity_type="PERSON",
        original="김민수",
    )

    assert result_before_expire == "[PERSON_1]"

    # TTL 만료 대기
    time.sleep(2)

    # 만료 후에는 조회되지 않아야 함
    result_after_expire = vault.get_token(
        session_id="ttl-test",
        entity_type="PERSON",
        original="김민수",
    )

    assert result_after_expire is None


def test_delete_session():
    vault = create_vault()

    vault.save_mapping(
        session_id="delete-session-test",
        entity_type="PERSON",
        original="김민수",
        token="[PERSON_1]",
    )

    vault.save_mapping(
        session_id="delete-session-test",
        entity_type="PHONE",
        original="010-1234-5678",
        token="[PHONE_1]",
    )

    vault.delete_session("delete-session-test")

    person_result = vault.get_token(
        session_id="delete-session-test",
        entity_type="PERSON",
        original="김민수",
    )

    phone_result = vault.get_token(
        session_id="delete-session-test",
        entity_type="PHONE",
        original="010-1234-5678",
    )

    assert person_result is None
    assert phone_result is None
