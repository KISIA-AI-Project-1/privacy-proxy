from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from privacy_proxy.vault.crypto import VaultCrypto, VaultCryptoError
from privacy_proxy.vault.store import InMemoryVaultStore
from privacy_proxy.vault.tokenizer import EntityMismatchError, Tokenizer, UnsupportedEntityError


@dataclass
class Ent:
    start_idx: int
    end_idx: int
    entity_type: str
    original_value: str
    confidence: float = 0.9


def ent(prompt: str, value: str, etype: str, nth: int = 0, conf: float = 0.9) -> Ent:
    idx = -1
    for _ in range(nth + 1):
        idx = prompt.index(value, idx + 1)
    return Ent(idx, idx + len(value), etype, value, conf)


@pytest.fixture
def crypto() -> VaultCrypto:
    return VaultCrypto.from_base64(VaultCrypto.generate_key())


@pytest.fixture
def tok(crypto: VaultCrypto) -> Tokenizer:
    return Tokenizer(InMemoryVaultStore(crypto), crypto)


def test_basic_anonymize_and_reveal(tok: Tokenizer) -> None:
    p = "김민수 고객의 주문번호 20260811-12345를 확인해주세요."
    r = tok.anonymize(
        session_id="s1",
        raw_prompt=p,
        detected_entities=[ent(p, "김민수", "PERSON_KO"), ent(p, "20260811-12345", "ORDER_ID")],
    )
    assert r.anonymized_prompt == "홍길동 고객의 주문번호 【ORDER_1】를 확인해주세요."
    assert "김민수" not in r.anonymized_prompt and "20260811" not in r.anonymized_prompt
    assert r.vault_mapping == {"홍길동": "김민수", "【ORDER_1】": "20260811-12345"}
    assert tok.reveal("s1", "【ORDER_1】") == "20260811-12345"


def test_same_value_same_pseudonym_and_phone_normalization(tok: Tokenizer) -> None:
    p = "010-1234-5678 그리고 +82 10 1234 5678"
    r = tok.anonymize(
        session_id="s1",
        raw_prompt=p,
        detected_entities=[
            ent(p, "010-1234-5678", "PHONE_NUMBER"),
            ent(p, "+82 10 1234 5678", "PHONE_NUMBER"),
        ],
    )
    assert r.anonymized_prompt == "【PHONE_1】 그리고 【PHONE_1】"


def test_sessions_are_isolated(tok: Tokenizer) -> None:
    p = "김민수"
    tok.anonymize(session_id="A", raw_prompt=p, detected_entities=[ent(p, "김민수", "PERSON_KO")])
    p2 = "이영희 김민수"
    r = tok.anonymize(
        session_id="B",
        raw_prompt=p2,
        detected_entities=[ent(p2, "이영희", "PERSON_KO"), ent(p2, "김민수", "PERSON_KO")],
    )
    assert r.anonymized_prompt == "홍길동 김하늘"
    assert tok.reveal("A", "김하늘") is None


def test_pseudonym_present_in_raw_prompt_is_skipped(tok: Tokenizer) -> None:
    p = "홍길동 팀장이 김민수 고객을 응대"
    r = tok.anonymize(
        session_id="s", raw_prompt=p, detected_entities=[ent(p, "김민수", "PERSON_KO")]
    )
    assert "김하늘" in r.anonymized_prompt and r.anonymized_prompt.startswith("홍길동 팀장")


def test_overlap_keeps_longest(tok: Tokenizer) -> None:
    p = "서울특별시 강남구 테헤란로 123 배송"
    full = ent(p, "서울특별시 강남구 테헤란로 123", "ADDRESS")
    part = ent(p, "테헤란로 123", "ADDRESS_ROAD")
    r = tok.anonymize(session_id="s", raw_prompt=p, detected_entities=[part, full])
    assert r.anonymized_prompt == "서울특별시 강남구 배송"
    assert r.vault_mapping == {}


def test_mismatch_raises_without_leaking_value(tok: Tokenizer) -> None:
    with pytest.raises(EntityMismatchError) as ei:
        tok.anonymize(
            session_id="s",
            raw_prompt="abc 김민수",
            detected_entities=[Ent(0, 3, "PERSON_KO", "김민수")],
        )
    assert "김민수" not in str(ei.value)


def test_unsupported_type_skipped_or_strict(crypto: VaultCrypto) -> None:
    p = "건강 상담"
    e = [Ent(0, 2, "SOME_NEW_TYPE", "건강")]
    r = Tokenizer(InMemoryVaultStore(crypto), crypto).anonymize(
        session_id="s", raw_prompt=p, detected_entities=e
    )
    assert r.skipped_types == ["SOME_NEW_TYPE"] and r.anonymized_prompt == p
    with pytest.raises(UnsupportedEntityError):
        Tokenizer(InMemoryVaultStore(crypto), crypto, strict=True).anonymize(
            session_id="s", raw_prompt=p, detected_entities=e
        )


def test_person_pool_exhaustion_fallback(tok: Tokenizer) -> None:
    names = [f"가나다{c}" for c in "라마바사아자차카타파하거너더러머버서어저처커터퍼허"]
    p = " ".join(names)
    r = tok.anonymize(
        session_id="s", raw_prompt=p, detected_entities=[ent(p, n, "PERSON_KO") for n in names]
    )
    assert len(set(r.vault_mapping)) == len(names)
    assert any(k.startswith("사용자") for k in r.vault_mapping)


def test_concurrent_same_value_single_pseudonym(tok: Tokenizer) -> None:
    p = "김민수"

    def run(_: int) -> str:
        return tok.anonymize(
            session_id="s", raw_prompt=p, detected_entities=[ent(p, "김민수", "PERSON_KO")]
        ).anonymized_prompt

    with ThreadPoolExecutor(16) as ex:
        assert len(set(ex.map(run, range(64)))) == 1


def test_crypto_aad_binding_and_bad_key(crypto: VaultCrypto) -> None:
    ct = crypto.encrypt("secret", aad="s1|PERSON")
    assert crypto.decrypt(ct, aad="s1|PERSON") == "secret"
    with pytest.raises(VaultCryptoError):
        crypto.decrypt(ct, aad="s2|PERSON")
    with pytest.raises(VaultCryptoError):
        VaultCrypto(b"short")


def test_delete_session(tok: Tokenizer) -> None:
    p = "김민수"
    tok.anonymize(session_id="s", raw_prompt=p, detected_entities=[ent(p, "김민수", "PERSON_KO")])
    assert tok.store.delete_session("s") > 0
    assert tok.reveal("s", "홍길동") is None


def test_existing_pseudonym_literal_in_prompt_gets_alias(tok: Tokenizer) -> None:
    p1 = "김민수"
    tok.anonymize(
        session_id="s", raw_prompt=p1, detected_entities=[ent(p1, "김민수", "PERSON_KO")]
    )  # 김민수 -> 홍길동
    p2 = "홍길동 팀장이 김민수 고객을 응대"  # '홍길동' 은 탐지되지 않은 진짜 텍스트
    r = tok.anonymize(
        session_id="s", raw_prompt=p2, detected_entities=[ent(p2, "김민수", "PERSON_KO")]
    )
    assert r.anonymized_prompt == "홍길동 팀장이 김하늘 고객을 응대"
    assert tok.reveal("s", "김하늘") == "김민수"  # alias
    assert tok.reveal("s", "홍길동") == "김민수"  # 기존 매핑 유지


def test_real_name_equal_to_pool_name_is_not_exposed(tok: Tokenizer) -> None:
    p = "홍길동 김민수"
    r = tok.anonymize(
        session_id="s",
        raw_prompt=p,
        detected_entities=[ent(p, "홍길동", "PERSON_KO"), ent(p, "김민수", "PERSON_KO")],
    )
    assert "홍길동" not in r.anonymized_prompt and "김민수" not in r.anonymized_prompt


def test_policy_quasi_identifiers(tok: Tokenizer) -> None:
    p = "서울특별시 강남구 34세"
    es = lambda: [ent(p, "서울특별시 강남구", "LOCATION"), ent(p, "34세", "AGE")]  # noqa: E731
    gen = tok.anonymize(
        session_id="a", raw_prompt=p, detected_entities=es(), policy_action="GENERALIZE"
    )
    assert gen.anonymized_prompt == "서울특별시 30대" and gen.vault_mapping == {}
    tk = tok.anonymize(
        session_id="b", raw_prompt=p, detected_entities=es(), policy_action="TOKENIZE"
    )
    assert tk.anonymized_prompt == "【LOCATION_1】 【AGE_1】"
    assert tok.reveal("b", "【AGE_1】") == "34세"
    none = tok.anonymize(session_id="c", raw_prompt=p, detected_entities=es(), policy_action=None)
    assert none.anonymized_prompt == p and set(none.passthrough_types) == {"LOCATION", "AGE"}


def test_address_by_policy_and_sensitive_always(tok: Tokenizer) -> None:
    p = "서울특별시 강남구 테헤란로 123 당뇨"

    def es():
        return [
            ent(p, "서울특별시 강남구 테헤란로 123", "ADDRESS"),
            ent(p, "당뇨", "SENSITIVE_HEALTH"),
        ]

    a = tok.anonymize(session_id="a", raw_prompt=p, detected_entities=es(), policy_action=None)
    assert a.anonymized_prompt == "서울특별시 강남구 【HEALTH_1】"
    b = tok.anonymize(
        session_id="b", raw_prompt=p, detected_entities=es(), policy_action="TOKENIZE"
    )
    assert b.anonymized_prompt == "【ADDR_1】 【HEALTH_1】"


def test_fallback_names_are_not_prefix_of_each_other(tok: Tokenizer) -> None:
    names = [f"가{c}{d}" for c in "나다라마바사아자차카" for d in "abcdefg"]  # 70명 -> 풀 소진
    p = " ".join(names)
    r = tok.anonymize(
        session_id="s", raw_prompt=p, detected_entities=[ent(p, n, "PERSON_KO") for n in names]
    )
    assert len(r.vault_mapping) == len(names)
    fallback = [k for k in r.vault_mapping if k.startswith("사용자[")]
    assert fallback and all(k.endswith("]") for k in fallback)
    assert all(
        not (a != b and a in b) for a in fallback for b in fallback
    )  # 서로 부분문자열이 아님
