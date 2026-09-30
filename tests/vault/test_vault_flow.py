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


def test_pii_tokenize_and_restore_flow():
    tokenizer = create_tokenizer()

    session_id = "e2e-test"

    # L3~L5 탐지 결과를 가정한 테스트 데이터
    detected_entities = [
        {
            "entity_type": "PERSON",
            "original": "김민수",
        },
        {
            "entity_type": "ORDER_ID",
            "original": "20260921-001",
        },
        {
            "entity_type": "PHONE",
            "original": "010-1234-5678",
        },
    ]

    original_prompt = "김민수 고객님의 주문번호는 20260921-001이며, 연락처는 010-1234-5678입니다."

    # 1. 탐지된 개인정보를 토큰으로 변환
    anonymized_prompt = original_prompt

    generated_tokens = {}

    for entity in detected_entities:
        entity_type = entity["entity_type"]
        original = entity["original"]

        token = tokenizer.tokenize(
            session_id=session_id,
            entity_type=entity_type,
            original=original,
        )

        generated_tokens[original] = token

        anonymized_prompt = anonymized_prompt.replace(
            original,
            token,
        )

    # 2. LLM에 전달되는 데이터에 원본 개인정보가 없어야 함
    assert "김민수" not in anonymized_prompt
    assert "20260921-001" not in anonymized_prompt
    assert "010-1234-5678" not in anonymized_prompt

    # 3. 토큰이 정상적으로 생성되었는지 확인
    assert generated_tokens["김민수"] == "[PERSON_1]"
    assert generated_tokens["20260921-001"] == "[ORDER_ID_1]"
    assert generated_tokens["010-1234-5678"] == "[PHONE_1]"

    # 4. 가명화된 Prompt 확인
    expected_anonymized_prompt = (
        "[PERSON_1] 고객님의 주문번호는 [ORDER_ID_1]이며, 연락처는 [PHONE_1]입니다."
    )

    assert anonymized_prompt == expected_anonymized_prompt

    # 5. LLM 응답을 가정
    llm_response = (
        "[PERSON_1] 고객님의 주문 [ORDER_ID_1]에 대한 "
        "문의가 접수되었습니다. "
        "연락처는 [PHONE_1]로 확인됩니다."
    )

    # 6. LLM 응답의 토큰을 원문으로 복원
    restored_response = llm_response

    for original, token in sorted(
        generated_tokens.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        entity_type = next(
            entity["entity_type"] for entity in detected_entities if entity["original"] == original
        )

        restored_original = tokenizer.restore(
            session_id=session_id,
            entity_type=entity_type,
            token=token,
        )

        assert restored_original == original

        restored_response = restored_response.replace(
            token,
            restored_original,
        )

    # 7. 최종 복원 결과 확인
    expected_response = (
        "김민수 고객님의 주문 20260921-001에 대한 "
        "문의가 접수되었습니다. "
        "연락처는 010-1234-5678로 확인됩니다."
    )

    assert restored_response == expected_response


def test_same_pii_reuses_same_token_multiple_times():
    tokenizer = create_tokenizer()

    session_id = "repeat-pii-test"

    # L3~L5 탐지 결과를 가정
    detected_entities = [
        {
            "entity_type": "PERSON",
            "original": "김민수",
        },
        {
            "entity_type": "ORDER_ID",
            "original": "20260921-001",
        },
    ]

    original_prompt = (
        "김민수님의 주문번호는 20260921-001입니다. "
        "김민수님이 주문번호 20260921-001에 대해 문의하셨습니다."
    )

    # 개인정보를 토큰으로 변환
    anonymized_prompt = original_prompt

    generated_tokens = {}

    for entity in detected_entities:
        entity_type = entity["entity_type"]
        original = entity["original"]

        token = tokenizer.tokenize(
            session_id=session_id,
            entity_type=entity_type,
            original=original,
        )

        generated_tokens[original] = token

        anonymized_prompt = anonymized_prompt.replace(
            original,
            token,
        )

    # 같은 개인정보가 여러 번 등장해도
    # 동일한 토큰을 사용해야 함
    expected_prompt = (
        "[PERSON_1]님의 주문번호는 [ORDER_ID_1]입니다. "
        "[PERSON_1]님이 주문번호 [ORDER_ID_1]에 대해 문의하셨습니다."
    )

    assert anonymized_prompt == expected_prompt

    # 같은 원문에 대해 생성된 토큰이 일관적인지 확인
    assert generated_tokens["김민수"] == "[PERSON_1]"
    assert generated_tokens["20260921-001"] == "[ORDER_ID_1]"

    # 토큰 복원
    restored_prompt = anonymized_prompt

    for entity in detected_entities:
        entity_type = entity["entity_type"]
        original = entity["original"]
        token = generated_tokens[original]

        restored_original = tokenizer.restore(
            session_id=session_id,
            entity_type=entity_type,
            token=token,
        )

        assert restored_original == original

        restored_prompt = restored_prompt.replace(
            token,
            restored_original,
        )

    # 최종적으로 원문과 동일하게 복원되는지 확인
    assert restored_prompt == original_prompt
