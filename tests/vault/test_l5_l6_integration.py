import pytest

from privacy_proxy.risk.score import assess_risk
from privacy_proxy.schemas import (
    DetectedPII,
    DetectionTier,
    ProxyContext,
)
from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore
from privacy_proxy.vault.tokenizer import EntityActionKind, Tokenizer


@pytest.fixture
def tokenizer():
    crypto = VaultCrypto(b"k" * 32)
    store = InMemoryVaultStore(crypto)
    return Tokenizer(store, crypto, strict=True)


def make_entity(prompt, value, entity_type, *, confidence=0.9):
    start = prompt.index(value)
    return DetectedPII(
        segment_id="seg-1",
        start_idx=start,
        end_idx=start + len(value),
        entity_type=entity_type,
        confidence=confidence,
        source="integration_test",
        tier=DetectionTier.DETERMINISTIC,
        original_value=value,
    )


def run_l5_l6(tokenizer, prompt, entities):
    context = ProxyContext(
        raw_prompt=prompt,
        detected_entities=entities,
    )

    # 실제 L5 위험도 평가 실행
    assess_risk(context)

    # L5 EntityPolicy 목록을 L6 입력 형식으로 변환
    entity_policies = {
        (p.segment_id, p.start_idx, p.end_idx): p.action for p in context.entity_policies
    }

    # 실제 L6 가명화 실행
    result = tokenizer.anonymize(
        session_id=context.session_id,
        raw_prompt=context.raw_prompt,
        detected_entities=context.detected_entities,
        policy_action=context.policy_action,
        entity_policies=entity_policies,
    )

    return context, result, entity_policies


def test_l5_direct_identifier_to_l6_tokenize(tokenizer):
    """직접식별자는 L5 TOKENIZE 정책에 따라 L6에서 가역 토큰화한다."""
    prompt = "고객 연락처는 010-1234-5678입니다."
    entity = make_entity(prompt, "010-1234-5678", "PHONE_NUMBER")

    context, result, _ = run_l5_l6(tokenizer, prompt, [entity])

    assert context.policy_action == "TOKENIZE"
    assert len(context.entity_policies) == 1

    assert result.anonymized_prompt != prompt
    assert "010-1234-5678" not in result.anonymized_prompt

    action = result.entity_actions[0]
    assert action.action == EntityActionKind.TOKENIZE

    pseudonym = next(iter(result.vault_mapping))
    assert tokenizer.reveal(context.session_id, pseudonym) == "010-1234-5678"


def test_l5_product_generalize_in_l6(tokenizer):
    """상품명은 L5 GENERALIZE 정책에 따라 L6에서 비가역 일반화한다."""
    prompt = "고객이 임신테스트기를 구매했습니다."
    entity = make_entity(prompt, "임신테스트기", "PRODUCT_ITEM")

    context, result, _ = run_l5_l6(tokenizer, prompt, [entity])

    assert any(
        p.entity_type == "PRODUCT_ITEM" and p.action == "GENERALIZE"
        for p in context.entity_policies
    )

    assert "상품" in result.anonymized_prompt
    assert "임신테스트기" not in result.anonymized_prompt

    action = next(a for a in result.entity_actions if a.entity_type == "PRODUCT_ITEM")
    assert action.action == EntityActionKind.GENERALIZE

    # 상품명은 가역 Vault에 저장하지 않는다.
    assert "임신테스트기" not in result.vault_mapping.values()


def test_l5_purchase_pattern_kept_in_l6(tokenizer):
    """PURCHASE_PATTERN은 L5에서 ALLOW, L6에서 원문 유지한다."""
    prompt = "고객의 구매 패턴은 매주 같은 상품을 구매하는 것입니다."
    value = "매주 같은 상품을 구매하는 것"
    entity = make_entity(prompt, value, "PURCHASE_PATTERN")

    context, result, _ = run_l5_l6(tokenizer, prompt, [entity])

    policy = next(p for p in context.entity_policies if p.entity_type == "PURCHASE_PATTERN")
    assert policy.action == "ALLOW"

    action = next(a for a in result.entity_actions if a.entity_type == "PURCHASE_PATTERN")
    assert action.action == EntityActionKind.KEEP
    assert value in result.anonymized_prompt


def test_l5_entity_policies_are_passed_to_l6(tokenizer):
    """L5의 항목별 정책이 요청 전체 정책보다 우선 전달되는지 확인한다."""
    prompt = "고객 연락처는 010-1234-5678입니다."
    entity = make_entity(prompt, "010-1234-5678", "PHONE_NUMBER")

    context = ProxyContext(
        raw_prompt=prompt,
        detected_entities=[entity],
    )
    assess_risk(context)

    policies = {(p.segment_id, p.start_idx, p.end_idx): p.action for p in context.entity_policies}

    # 요청 전체 정책을 ALLOW로 바꾸더라도 개별 정책 TOKENIZE가 우선한다.
    result = tokenizer.anonymize(
        session_id=context.session_id,
        raw_prompt=prompt,
        detected_entities=context.detected_entities,
        policy_action="ALLOW",
        entity_policies=policies,
    )

    assert result.anonymized_prompt != prompt
    assert "010-1234-5678" not in result.anonymized_prompt
    assert result.entity_actions[0].action == EntityActionKind.TOKENIZE


def test_l5_result_contains_entity_policies(tokenizer):
    """L5 평가 결과에 엔티티별 정책이 생성되는지 확인한다."""
    prompt = "홍길동의 연락처는 010-1234-5678입니다."

    entities = [
        make_entity(prompt, "홍길동", "PERSON_KO"),
        make_entity(prompt, "010-1234-5678", "PHONE_NUMBER"),
    ]

    context = ProxyContext(
        raw_prompt=prompt,
        detected_entities=entities,
    )

    assess_risk(context)

    assert context.risk_score >= 80
    assert context.policy_action == "TOKENIZE"
    assert len(context.entity_policies) == 2

    assert all(policy.action == "TOKENIZE" for policy in context.entity_policies)


@pytest.mark.parametrize(
    ("entity_type", "value"),
    [
        ("KR_PASSPORT", "M12345678"),
        ("CUSTOMER_ID", "CUST-12345"),
        ("TRACKING_NUMBER", "123456789012"),
    ],
)
def test_l5_service_identifiers_tokenize_in_l6(tokenizer, entity_type, value):
    """여권번호와 서비스 식별자는 L5 TOKENIZE 정책에 따라 L6에서 가역 토큰화한다."""
    prompt = f"고객 식별 정보는 {value}입니다."
    entity = make_entity(prompt, value, entity_type)

    context, result, _ = run_l5_l6(tokenizer, prompt, [entity])

    # L5가 해당 엔티티에 TOKENIZE를 지정했는지 확인
    policy = next(p for p in context.entity_policies if p.entity_type == entity_type)
    assert policy.action == "TOKENIZE"

    # L6에서 원문이 제거되고 토큰으로 치환됐는지 확인
    assert result.anonymized_prompt != prompt
    assert value not in result.anonymized_prompt

    action = next(a for a in result.entity_actions if a.entity_type == entity_type)
    assert action.action == EntityActionKind.TOKENIZE

    # Vault에 저장된 토큰으로 원문 복원이 가능한지 확인
    pseudonym = next(token for token, original in result.vault_mapping.items() if original == value)
    assert tokenizer.reveal(context.session_id, pseudonym) == value
