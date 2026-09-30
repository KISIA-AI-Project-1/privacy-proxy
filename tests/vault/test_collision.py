import redis

from privacy_proxy.vault.collision import TokenCollisionManager


def create_manager() -> TokenCollisionManager:
    client = redis.Redis(host="localhost", port=6379)
    return TokenCollisionManager(client)


def test_generate_token():
    manager = create_manager()

    token1 = manager.generate_token(
        session_id="collision-test",
        entity_type="PERSON",
    )

    token2 = manager.generate_token(
        session_id="collision-test",
        entity_type="PERSON",
    )

    assert token1 != token2
    assert token1.startswith("[PERSON_")
    assert token2.startswith("[PERSON_")


def test_entity_type_is_separated():
    manager = create_manager()

    person_token = manager.generate_token(
        session_id="type-test",
        entity_type="PERSON",
    )

    phone_token = manager.generate_token(
        session_id="type-test",
        entity_type="PHONE",
    )

    assert person_token == "[PERSON_1]"
    assert phone_token == "[PHONE_1]"
