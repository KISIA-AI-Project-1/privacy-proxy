import redis
from cryptography.fernet import Fernet

from privacy_proxy.vault.collision import TokenCollisionManager
from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import SessionVault
from privacy_proxy.vault.tokenizer import Tokenizer


def create_tokenizer() -> Tokenizer:
    client = redis.Redis(host="localhost", port=6379)

    key = Fernet.generate_key().decode()
    crypto = VaultCrypto(key)

    vault = SessionVault(
        redis_client=client,
        crypto=crypto,
        ttl=1800,
    )

    collision_manager = TokenCollisionManager(client)

    return Tokenizer(
        vault=vault,
        collision_manager=collision_manager,
    )


def test_same_original_reuses_token():
    tokenizer = create_tokenizer()

    token1 = tokenizer.tokenize(
        session_id="tokenizer-test-1",
        entity_type="PERSON",
        original="김민수",
    )

    token2 = tokenizer.tokenize(
        session_id="tokenizer-test-1",
        entity_type="PERSON",
        original="김민수",
    )

    assert token1 == token2


def test_different_original_gets_different_token():
    tokenizer = create_tokenizer()

    token1 = tokenizer.tokenize(
        session_id="tokenizer-test-2",
        entity_type="PERSON",
        original="김민수",
    )

    token2 = tokenizer.tokenize(
        session_id="tokenizer-test-2",
        entity_type="PERSON",
        original="이영희",
    )

    assert token1 != token2


def test_different_session_is_separated():
    tokenizer = create_tokenizer()

    token_a = tokenizer.tokenize(
        session_id="session-a",
        entity_type="PERSON",
        original="김민수",
    )

    token_b = tokenizer.tokenize(
        session_id="session-b",
        entity_type="PERSON",
        original="김민수",
    )

    assert token_a == "[PERSON_1]"
    assert token_b == "[PERSON_1]"

    token_a_again = tokenizer.tokenize(
        session_id="session-a",
        entity_type="PERSON",
        original="김민수",
    )

    assert token_a_again == token_a


def test_restore_token_to_original():
    tokenizer = create_tokenizer()

    original = "김민수"

    token = tokenizer.tokenize(
        session_id="restore-test-1",
        entity_type="PERSON",
        original=original,
    )

    restored = tokenizer.restore(
        session_id="restore-test-1",
        entity_type="PERSON",
        token=token,
    )

    assert restored == original


def test_restore_unknown_token_returns_none():
    tokenizer = create_tokenizer()

    restored = tokenizer.restore(
        session_id="restore-test-2",
        entity_type="PERSON",
        token="[PERSON_999]",
    )

    assert restored is None


def test_restore_token_from_different_session_returns_none():
    tokenizer = create_tokenizer()

    token = tokenizer.tokenize(
        session_id="restore-session-a",
        entity_type="PERSON",
        original="김민수",
    )

    restored = tokenizer.restore(
        session_id="restore-session-b",
        entity_type="PERSON",
        token=token,
    )

    assert restored is None
