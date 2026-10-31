"""L6 Vault 단위 테스트. Redis 없이 InMemoryVaultStore 로 돈다.

uv run pytest tests/test_vault.py -v
"""

from __future__ import annotations

import os

import pytest

from privacy_proxy.schemas import DetectedPII, DetectionTier
from privacy_proxy.vault import (
    CreateStatus,
    EntityActionKind,
    EntityMismatchError,
    InMemoryVaultStore,
    MappingRecord,
    Tokenizer,
    UnsupportedEntityError,
    VaultCrypto,
    VaultCryptoError,
)
from privacy_proxy.vault.tokenizer import POLICY_SPECS, resolve_spec

SID = "session-a"


# ---------------------------------------------------------------- 헬퍼
def make_det(prompt: str, value: str, entity_type: str, *, nth: int = 0) -> DetectedPII:
    """prompt 안에서 value 의 nth 번째 등장 위치로 DetectedPII 를 만든다."""
    start = -1
    for _ in range(nth + 1):
        start = prompt.index(value, start + 1)
    return DetectedPII(
        start_idx=start,
        end_idx=start + len(value),
        entity_type=entity_type,
        confidence=0.9,
        source="TEST",
        tier=DetectionTier.RULE_ANCHORED,
        original_value=value,
        normalized=value,
    )


@pytest.fixture
def crypto() -> VaultCrypto:
    return VaultCrypto(os.urandom(32))


@pytest.fixture
def store(crypto: VaultCrypto) -> InMemoryVaultStore:
    return InMemoryVaultStore(crypto)


@pytest.fixture
def tok(store: InMemoryVaultStore, crypto: VaultCrypto) -> Tokenizer:
    return Tokenizer(store, crypto, strict=True)


# ---------------------------------------------------------------- 정책 표
class TestPolicyTable:
    @pytest.mark.parametrize("policy", ["TOKENIZE", "GENERALIZE", "ALLOW", None, "UNKNOWN"])
    def test_purchase_pattern_always_none(self, policy: str | None) -> None:
        assert "PURCHASE_PATTERN" in POLICY_SPECS
        assert resolve_spec("PURCHASE_PATTERN", policy) is None

    def test_direct_identifier_ignores_policy(self) -> None:
        for policy in ("TOKENIZE", "GENERALIZE", "ALLOW", None):
            assert resolve_spec("PHONE_NUMBER", policy) is not None
            assert resolve_spec("SENSITIVE_HEALTH", policy) is not None

    @pytest.mark.parametrize(
        "policy",
        ["TOKENIZE", "GENERALIZE", "ALLOW", None, "UNKNOWN"],
    )
    def test_product_item_always_generalized(self, policy: str | None) -> None:
        assert resolve_spec("PRODUCT_ITEM", policy) is not None
        assert resolve_spec("PRODUCT_ITEM", policy) == POLICY_SPECS["PRODUCT_ITEM"]["*"]


# ---------------------------------------------------------------- PURCHASE_PATTERN 통과
class TestPurchasePatternPassthrough:
    @pytest.mark.parametrize("policy", ["TOKENIZE", "GENERALIZE", "ALLOW", None])
    def test_kept_in_every_policy(self, tok: Tokenizer, policy: str | None) -> None:
        prompt = "3개월 주기 정기배송 배송지 변경 부탁드립니다"
        det = make_det(prompt, "정기배송", "PURCHASE_PATTERN")

        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action=policy
        )

        assert result.anonymized_prompt == prompt
        assert result.vault_mapping == {}
        assert result.passthrough_types == ["PURCHASE_PATTERN"]
        assert [a.action for a in result.entity_actions] == [EntityActionKind.KEEP]

    def test_no_exception_in_strict_mode(self, tok: Tokenizer) -> None:
        # strict 는 미지원 타입만 막는다. PURCHASE_PATTERN 은 지원 + 통과.
        prompt = "정기배송 신청"
        det = make_det(prompt, "정기배송", "PURCHASE_PATTERN")
        tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="TOKENIZE"
        )


# ---------------------------------------------------------------- 기본 치환
class TestBasicTokenization:
    def test_phone_tokenized_even_if_allow(self, tok: Tokenizer) -> None:
        prompt = "연락처는 010-1234-5678 입니다"
        det = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")

        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="ALLOW"
        )

        assert result.anonymized_prompt == "연락처는 【PHONE_1】 입니다"
        assert result.vault_mapping == {"【PHONE_1】": "010-1234-5678"}
        assert result.token_types == {"【PHONE_1】": "PHONE_NUMBER"}

    def test_health_has_hint(self, tok: Tokenizer) -> None:
        prompt = "저는 우울증이 있어요"
        det = make_det(prompt, "우울증", "SENSITIVE_HEALTH")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="TOKENIZE"
        )
        assert "【HEALTH_1:건강정보】" in result.anonymized_prompt
        assert "우울증" not in result.anonymized_prompt

    def test_person_gets_natural_pseudonym(self, tok: Tokenizer) -> None:
        prompt = "저 김철수인데요"
        det = make_det(prompt, "김철수", "PERSON_KO")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="ALLOW"
        )
        assert result.anonymized_prompt == "저 홍길동인데요"
        assert tok.reveal(SID, "홍길동") == "김철수"

    def test_product_item_always_generalized(self, tok: Tokenizer) -> None:
        prompt = "프로페시아 샀어요"
        det = make_det(prompt, "프로페시아", "PRODUCT_ITEM")

        for policy in ("ALLOW", "TOKENIZE", "GENERALIZE", None):
            result = tok.anonymize(
                session_id=SID,
                raw_prompt=prompt,
                detected_entities=[det],
                policy_action=policy,
            )

            assert result.anonymized_prompt == "상품 샀어요"
            assert result.vault_mapping == {}
            assert result.token_types == {}
            assert result.entity_actions[0].action is EntityActionKind.GENERALIZE


# ---------------------------------------------------------------- 주소 / 일반화
class TestAddressAndGeneralize:
    def test_address_road_masked_by_default(self, tok: Tokenizer) -> None:
        prompt = "주소는 월드컵북로4길 77 입니다"
        det = make_det(prompt, "월드컵북로4길 77", "ADDRESS_ROAD")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="ALLOW"
        )
        assert result.anonymized_prompt == "주소는 【ADDRESS】 입니다"
        assert result.vault_mapping == {}  # 비가역: Vault 에 저장 안 함
        assert result.entity_actions[0].action is EntityActionKind.GENERALIZE

    def test_address_road_tokenized_when_l5_tokenize(self, tok: Tokenizer) -> None:
        prompt = "주소는 월드컵북로4길 77 입니다"
        det = make_det(prompt, "월드컵북로4길 77", "ADDRESS_ROAD")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="TOKENIZE"
        )
        assert result.anonymized_prompt == "주소는 【ADDR_ROAD_1】 입니다"
        assert tok.reveal(SID, "【ADDR_ROAD_1】") == "월드컵북로4길 77"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("서울 마포구 신림동", "서울"), ("서울특별시", "서울특별시"), ("관악구", "【LOCATION】")],
    )
    def test_location_generalize(self, tok: Tokenizer, value: str, expected: str) -> None:
        prompt = f"{value}에 살아요"
        det = make_det(prompt, value, "LOCATION")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="GENERALIZE"
        )
        assert result.anonymized_prompt == f"{expected}에 살아요"

    def test_age_generalize(self, tok: Tokenizer) -> None:
        prompt = "저는 34세입니다"
        det = make_det(prompt, "34세", "AGE")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="GENERALIZE"
        )
        assert result.anonymized_prompt == "저는 30대입니다"


# ---------------------------------------------------------------- LOCATION_INFORMAL 일반화
class TestLocationInformal:
    def test_generalize_is_irreversible(self, tok: Tokenizer) -> None:
        prompt = "신림동에 살아요"
        det = make_det(prompt, "신림동", "LOCATION_INFORMAL")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="GENERALIZE"
        )
        assert result.anonymized_prompt == "【LOCATION】에 살아요"
        assert result.vault_mapping == {}
        assert result.entity_actions[0].action is EntityActionKind.GENERALIZE

    def test_tokenize_still_reversible(self, tok: Tokenizer) -> None:
        prompt = "신림동에 살아요"
        det = make_det(prompt, "신림동", "LOCATION_INFORMAL")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="TOKENIZE"
        )
        assert result.anonymized_prompt == "【LOCATION_1】에 살아요"
        assert tok.reveal(SID, "【LOCATION_1】") == "신림동"

    def test_same_result_as_location(self, tok: Tokenizer) -> None:
        # 중복 탐지로 어느 타입이 남아도 결과가 같아야 한다.
        prompt = "신림동에 살아요"
        a = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[make_det(prompt, "신림동", "LOCATION")],
            policy_action="GENERALIZE",
        )
        b = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[make_det(prompt, "신림동", "LOCATION_INFORMAL")],
            policy_action="GENERALIZE",
        )
        assert a.anonymized_prompt == b.anonymized_prompt == "【LOCATION】에 살아요"


# ---------------------------------------------------------------- 시나리오 A (B2B)
class TestScenarioA:
    PROMPT = (
        "안녕하세요, 저 김철수인데요. 지난달부터 3개월 주기 정기배송으로 신청한 "
        "프로페시아 배송지 변경 부탁드립니다. 010-1234-5678로 연락 주시고 "
        "주소는 월드컵북로4길 77입니다."
    )

    def _dets(self) -> list[DetectedPII]:
        p = self.PROMPT
        return [
            make_det(p, "김철수", "PERSON_KO"),
            make_det(p, "정기배송", "PURCHASE_PATTERN"),
            make_det(p, "프로페시아", "PRODUCT_ITEM"),
            make_det(p, "010-1234-5678", "PHONE_NUMBER"),
            make_det(p, "월드컵북로4길 77", "ADDRESS_ROAD"),
        ]

    def test_end_to_end(self, tok: Tokenizer) -> None:
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=self.PROMPT,
            detected_entities=self._dets(),
            policy_action="TOKENIZE",
        )
        out = result.anonymized_prompt

        # 보호
        for secret in ("김철수", "프로페시아", "010-1234-5678", "월드컵북로4길"):
            assert secret not in out
        # 유지(업무상 필요)
        assert "정기배송" in out
        assert "배송지 변경" in out
        # 토큰 확인
        assert "【PHONE_1】" in out
        assert "상품" in out
        assert "【ADDR_ROAD_1】" in out

        # 복원
        for token, original in result.vault_mapping.items():
            assert tok.reveal(SID, token) == original

    def test_entity_actions_per_span(self, tok: Tokenizer) -> None:
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=self.PROMPT,
            detected_entities=self._dets(),
            policy_action="TOKENIZE",
        )
        by_type = {a.entity_type: a.action for a in result.entity_actions}
        assert by_type == {
            "PERSON_KO": EntityActionKind.TOKENIZE,
            "PURCHASE_PATTERN": EntityActionKind.KEEP,
            "PRODUCT_ITEM": EntityActionKind.GENERALIZE,
            "PHONE_NUMBER": EntityActionKind.TOKENIZE,
            "ADDRESS_ROAD": EntityActionKind.TOKENIZE,
        }
        # 좌표는 raw_prompt 기준이고 원문 값은 담지 않는다.
        for action in result.entity_actions:
            assert 0 <= action.start_idx < action.end_idx <= len(self.PROMPT)
            assert not hasattr(action, "original_value")


# ---------------------------------------------------------------- 항목별 정책(entity_policies)
class TestEntityPolicies:
    def test_purchase_pattern_kept_even_if_entity_policy_says_tokenize(
        self, tok: Tokenizer
    ) -> None:
        prompt = "3개월 주기 정기배송 변경"
        det = make_det(prompt, "정기배송", "PURCHASE_PATTERN")
        for action in ("TOKENIZE", "GENERALIZE", "ALLOW"):
            result = tok.anonymize(
                session_id=SID,
                raw_prompt=prompt,
                detected_entities=[det],
                policy_action="TOKENIZE",
                entity_policies={("seg-1", det.start_idx, det.end_idx): action},
            )
            assert result.anonymized_prompt == prompt
            assert result.entity_actions[0].action is EntityActionKind.KEEP

    def test_entity_policy_overrides_request_policy(self, tok: Tokenizer) -> None:
        prompt = "30대이고 연락처는 010-1234-5678 입니다"
        age = make_det(prompt, "30대", "AGE_GROUP")
        phone = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[age, phone],
            policy_action="TOKENIZE",  # 요청 단위로는 AGE_GROUP 도 가려질 상황
            entity_policies={
                ("seg-1", age.start_idx, age.end_idx): "ALLOW",
                ("seg-1", phone.start_idx, phone.end_idx): "TOKENIZE",
            },
        )
        assert result.anonymized_prompt == "30대이고 연락처는 【PHONE_1】 입니다"

    def test_missing_key_raises_error(self, tok: Tokenizer) -> None:
        prompt = "30대입니다"
        age = make_det(prompt, "30대", "AGE_GROUP")

        with pytest.raises(ValueError, match="L5 entity policy missing"):
            tok.anonymize(
                session_id=SID,
                raw_prompt=prompt,
                detected_entities=[age],
                policy_action="TOKENIZE",
                entity_policies={},  # 키 없음
            )

    def test_direct_identifier_ignores_entity_policy(self, tok: Tokenizer) -> None:
        prompt = "번호 010-1234-5678"
        phone = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[phone],
            entity_policies={("seg-1", phone.start_idx, phone.end_idx): "ALLOW"},
        )
        assert result.anonymized_prompt == "번호 【PHONE_1】"

    def test_address_masked_even_if_l5_allow(self, tok: Tokenizer) -> None:
        # L5 는 ALLOW 라고 해도 L6 실제 처리는 마스킹. 화면은 이 결과를 보여야 한다.
        prompt = "주소는 월드컵북로4길 77 입니다"
        det = make_det(prompt, "월드컵북로4길 77", "ADDRESS_ROAD")
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[det],
            policy_action="ALLOW",
            entity_policies={("seg-1", det.start_idx, det.end_idx): "ALLOW"},
        )
        assert result.anonymized_prompt == "주소는 【ADDRESS】 입니다"
        assert result.entity_actions[0].action is EntityActionKind.GENERALIZE

    def test_entity_action_has_segment_id_for_join(self, tok: Tokenizer) -> None:
        prompt = "번호 010-1234-5678"
        phone = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[phone])
        a = result.entity_actions[0]
        assert (a.segment_id, a.start_idx, a.end_idx) == ("seg-1", phone.start_idx, phone.end_idx)

    def test_product_item_generalize_is_irreversible(self, tok: Tokenizer) -> None:
        # PRODUCT_ITEM 은 GENERALIZE 시 구체적인 상품명을 "상품"으로 일반화한다.
        prompt = "프로페시아 샀어요"
        det = make_det(prompt, "프로페시아", "PRODUCT_ITEM")
        result = tok.anonymize(
            session_id=SID,
            raw_prompt=prompt,
            detected_entities=[det],
            entity_policies={("seg-1", det.start_idx, det.end_idx): "GENERALIZE"},
        )
        assert result.anonymized_prompt == "상품 샀어요"
        assert result.vault_mapping == {}
        assert result.entity_actions[0].action is EntityActionKind.GENERALIZE


# ---------------------------------------------------------------- 일관성 / 세션
class TestConsistency:
    def test_same_value_same_token_within_request(self, tok: Tokenizer) -> None:
        prompt = "010-1234-5678 로 연락 주세요. 다시 말씀드리면 010-1234-5678 입니다."
        dets = [
            make_det(prompt, "010-1234-5678", "PHONE_NUMBER", nth=0),
            make_det(prompt, "010-1234-5678", "PHONE_NUMBER", nth=1),
        ]
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=dets, policy_action="ALLOW"
        )
        assert result.anonymized_prompt.count("【PHONE_1】") == 2
        assert "【PHONE_2】" not in result.anonymized_prompt

    def test_same_token_across_requests_in_session(self, tok: Tokenizer) -> None:
        p1 = "번호 010-1234-5678"
        p2 = "다시 010-1234-5678 입니다"
        r1 = tok.anonymize(
            session_id=SID,
            raw_prompt=p1,
            detected_entities=[make_det(p1, "010-1234-5678", "PHONE_NUMBER")],
        )
        r2 = tok.anonymize(
            session_id=SID,
            raw_prompt=p2,
            detected_entities=[make_det(p2, "010-1234-5678", "PHONE_NUMBER")],
        )
        assert "【PHONE_1】" in r1.anonymized_prompt
        assert "【PHONE_1】" in r2.anonymized_prompt

    def test_phone_format_variants_share_token(self, tok: Tokenizer) -> None:
        p1 = "번호 010-1234-5678"
        p2 = "번호 +82 10-1234-5678"
        r1 = tok.anonymize(
            session_id=SID,
            raw_prompt=p1,
            detected_entities=[make_det(p1, "010-1234-5678", "PHONE_NUMBER")],
        )
        r2 = tok.anonymize(
            session_id=SID,
            raw_prompt=p2,
            detected_entities=[make_det(p2, "+82 10-1234-5678", "PHONE_NUMBER")],
        )
        assert r1.anonymized_prompt.endswith("【PHONE_1】")
        assert r2.anonymized_prompt.endswith("【PHONE_1】")

    def test_different_values_get_different_tokens(self, tok: Tokenizer) -> None:
        prompt = "A 010-1111-2222 B 010-3333-4444"
        dets = [
            make_det(prompt, "010-1111-2222", "PHONE_NUMBER"),
            make_det(prompt, "010-3333-4444", "PHONE_NUMBER"),
        ]
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=dets)
        assert result.anonymized_prompt == "A 【PHONE_1】 B 【PHONE_2】"

    def test_sessions_are_isolated(self, tok: Tokenizer) -> None:
        prompt = "번호 010-1234-5678"
        det = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")
        tok.anonymize(session_id="session-a", raw_prompt=prompt, detected_entities=[det])

        assert tok.reveal("session-a", "【PHONE_1】") == "010-1234-5678"
        assert tok.reveal("session-b", "【PHONE_1】") is None


# ---------------------------------------------------------------- 가명 충돌
class TestCollision:
    def test_pseudonym_never_equals_real_text(self, tok: Tokenizer) -> None:
        # 원문에 진짜 '홍길동'이 있으면 가명 풀의 첫 번째(홍길동)를 쓰면 안 된다.
        prompt = "홍길동님과 김철수님"
        dets = [make_det(prompt, "홍길동", "PERSON_KO"), make_det(prompt, "김철수", "PERSON_KO")]
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=dets, policy_action="ALLOW"
        )
        assert "홍길동" not in result.anonymized_prompt
        assert "김철수" not in result.anonymized_prompt
        assert tok.reveal(SID, "성춘향") == "홍길동"
        assert tok.reveal(SID, "이몽룡") == "김철수"

    def test_token_literal_already_in_prompt(self, tok: Tokenizer) -> None:
        # 사용자가 우연히 '【PHONE_1】' 을 직접 쓴 경우 다른 번호를 붙인다.
        prompt = "【PHONE_1】 그리고 010-1234-5678"
        det = make_det(prompt, "010-1234-5678", "PHONE_NUMBER")
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[det])
        assert result.anonymized_prompt == "【PHONE_1】 그리고 【PHONE_2】"


# ---------------------------------------------------------------- 오류 처리
class TestErrors:
    def test_span_mismatch_raises(self, tok: Tokenizer) -> None:
        prompt = "번호 010-1234-5678"
        bad = DetectedPII(
            start_idx=3,
            end_idx=16,
            entity_type="PHONE_NUMBER",
            confidence=0.9,
            source="TEST",
            tier=DetectionTier.RULE_ANCHORED,
            original_value="010-0000-0000",  # 원문과 다름
        )
        with pytest.raises(EntityMismatchError):
            tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[bad])

    def test_unknown_type_strict_raises(self, tok: Tokenizer) -> None:
        prompt = "무언가 XYZ"
        det = make_det(prompt, "XYZ", "SOME_NEW_TYPE")
        with pytest.raises(UnsupportedEntityError):
            tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[det])

    def test_unknown_type_non_strict_skipped(
        self, store: InMemoryVaultStore, crypto: VaultCrypto
    ) -> None:
        lenient = Tokenizer(store, crypto, strict=False)
        prompt = "무언가 XYZ"
        det = make_det(prompt, "XYZ", "SOME_NEW_TYPE")
        result = lenient.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[det])
        assert result.anonymized_prompt == prompt
        assert result.skipped_types == ["SOME_NEW_TYPE"]
        assert result.entity_actions[0].action is EntityActionKind.SKIPPED

    def test_no_entities_returns_prompt_unchanged(self, tok: Tokenizer) -> None:
        result = tok.anonymize(session_id=SID, raw_prompt="안녕하세요", detected_entities=[])
        assert result.anonymized_prompt == "안녕하세요"
        assert result.entity_actions == []


# ---------------------------------------------------------------- crypto
class TestCrypto:
    def test_roundtrip(self, crypto: VaultCrypto) -> None:
        enc = crypto.encrypt("010-1234-5678", aad="s|PHONE_NUMBER")
        assert "010" not in enc
        assert crypto.decrypt(enc, aad="s|PHONE_NUMBER") == "010-1234-5678"

    def test_wrong_aad_fails(self, crypto: VaultCrypto) -> None:
        enc = crypto.encrypt("secret", aad="s1|PHONE_NUMBER")
        with pytest.raises(VaultCryptoError):
            crypto.decrypt(enc, aad="s2|PHONE_NUMBER")

    def test_same_plaintext_different_ciphertext(self, crypto: VaultCrypto) -> None:
        a = crypto.encrypt("x", aad="a")
        b = crypto.encrypt("x", aad="a")
        assert a != b  # nonce 랜덤

    def test_bad_key_length(self) -> None:
        with pytest.raises(VaultCryptoError):
            VaultCrypto(b"short")

    def test_from_base64_roundtrip(self) -> None:
        key = VaultCrypto.generate_key()
        assert isinstance(VaultCrypto.from_base64(key), VaultCrypto)

    def test_from_base64_invalid(self) -> None:
        with pytest.raises(VaultCryptoError):
            VaultCrypto.from_base64("%%%not-base64%%%")

    def test_lookup_key_deterministic_and_separated(self, crypto: VaultCrypto) -> None:
        assert crypto.lookup_key("a", "b") == crypto.lookup_key("a", "b")
        assert crypto.lookup_key("a", "b") != crypto.lookup_key("ab", "")  # 구분자 충돌 방지


# ---------------------------------------------------------------- store
class TestStore:
    def test_create_existing_collision(self, store: InMemoryVaultStore) -> None:
        rec = MappingRecord("PHONE_NUMBER", "【PHONE_1】", "enc1")
        assert store.create_mapping(SID, "PHONE_NUMBER", "0101", rec).status is CreateStatus.CREATED
        # 같은 원문 -> EXISTING
        again = store.create_mapping(SID, "PHONE_NUMBER", "0101", rec)
        assert again.status is CreateStatus.EXISTING
        # 다른 원문이 같은 가명 -> COLLISION
        other = store.create_mapping(SID, "PHONE_NUMBER", "0202", rec)
        assert other.status is CreateStatus.COLLISION
        assert other.record is None

    def test_alias(self, store: InMemoryVaultStore) -> None:
        base = MappingRecord("PERSON_KO", "홍길동", "enc")
        store.create_mapping(SID, "PERSON", "김철수", base)
        alias = MappingRecord("PERSON_KO", "성춘향", "enc")
        assert store.add_alias(SID, alias) is True
        assert store.add_alias(SID, alias) is False  # 이미 사용 중
        rec = store.get_by_pseudonym(SID, "성춘향")
        assert rec is not None
        assert rec.original_enc == "enc"

    def test_counter_per_type(self, store: InMemoryVaultStore) -> None:
        assert store.next_counter(SID, "PHONE_NUMBER") == 1
        assert store.next_counter(SID, "PHONE_NUMBER") == 2
        assert store.next_counter(SID, "EMAIL_ADDRESS") == 1

    def test_delete_session(self, store: InMemoryVaultStore) -> None:
        store.create_mapping(
            SID, "PHONE_NUMBER", "0101", MappingRecord("PHONE_NUMBER", "【P】", "e")
        )
        store.next_counter(SID, "PHONE_NUMBER")
        assert store.delete_session(SID) > 0
        assert store.get_by_pseudonym(SID, "【P】") is None

    @pytest.mark.parametrize("bad", ["", "has space", "a*b", "x" * 129, "a:b"])
    def test_invalid_session_id_rejected(self, store: InMemoryVaultStore, bad: str) -> None:
        with pytest.raises(ValueError):
            store.pseudonym_exists(bad, "x")


# ---------------------------------------------------------------- 조사 보정(전체 치환)
class TestJosaCorrection:
    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            ("가 문의했어요", "홍길동이 문의했어요"),  # 철수(받침 없음) -> 길동(받침 있음)
            ("는 환불을 원해요", "홍길동은 환불을 원해요"),
            ("를 찾아요", "홍길동을 찾아요"),
            ("와 통화", "홍길동과 통화"),
            ("로 보내주세요", "홍길동으로 보내주세요"),
        ],
    )
    def test_person_pseudonym(self, tok: Tokenizer, suffix: str, expected: str) -> None:
        prompt = "김철수" + suffix
        det = make_det(prompt, "김철수", "PERSON_KO")
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=[det])
        assert result.anonymized_prompt == expected
        assert result.vault_mapping == {"홍길동": "김철수"}  # 키에 조사 없음

    @pytest.mark.parametrize(
        ("value", "suffix", "expected"),
        [
            ("서울 마포구 신림동", "은 좋아요", "서울은 좋아요"),  # 동(받침) -> 서울(받침)
            ("서울 마포구 신림동", "으로 이사", "서울로 이사"),  # ㄹ 받침은 '로'
            ("부산광역시 해운대구 우동", "을 좋아해요", "부산광역시를 좋아해요"),  # 받침 없음
        ],
    )
    def test_generalized_location(
        self, tok: Tokenizer, value: str, suffix: str, expected: str
    ) -> None:
        prompt = value + suffix
        det = make_det(prompt, value, "LOCATION")
        result = tok.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=[det], policy_action="GENERALIZE"
        )
        assert result.anonymized_prompt == expected

    def test_bracket_token_keeps_original_josa(self, tok: Tokenizer) -> None:
        prompt = "010-1234-5678로 연락, 010-1234-5678은 제 번호"
        dets = [
            make_det(prompt, "010-1234-5678", "PHONE_NUMBER", nth=0),
            make_det(prompt, "010-1234-5678", "PHONE_NUMBER", nth=1),
        ]
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=dets)
        assert result.anonymized_prompt == "【PHONE_1】로 연락, 【PHONE_1】은 제 번호"

    def test_not_josa_when_word_continues(self, tok: Tokenizer) -> None:
        prompt = "김철수가격 김철수이메일"
        dets = [
            make_det(prompt, "김철수", "PERSON_KO", nth=0),
            make_det(prompt, "김철수", "PERSON_KO", nth=1),
        ]
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=dets)
        assert result.anonymized_prompt == "홍길동가격 홍길동이메일"

    def test_josa_not_swallowed_across_next_entity(self, tok: Tokenizer) -> None:
        prompt = "김철수와 이영희"
        dets = [make_det(prompt, "김철수", "PERSON_KO"), make_det(prompt, "이영희", "PERSON_KO")]
        result = tok.anonymize(session_id=SID, raw_prompt=prompt, detected_entities=dets)
        assert result.anonymized_prompt == "홍길동과 성춘향"
