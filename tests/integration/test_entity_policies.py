"""항목별 보호 정책(L5 entity_policies → L6) 회귀 테스트.

예전에는 policy_action 하나가 요청 전체에 적용돼서, 전화번호 하나만 있어도
연령·지역 같은 준식별자까지 전부 토큰화됐다.
"""

import os

import pytest

from privacy_proxy.risk.score import assess_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext
from privacy_proxy.vault import Tokenizer, VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore


def _det(text: str, value: str, entity_type: str, tier: DetectionTier) -> DetectedPII:
    start = text.index(value)
    return DetectedPII(
        start_idx=start,
        end_idx=start + len(value),
        entity_type=entity_type,
        confidence=None,
        source=f"test_{entity_type}",
        tier=tier,
        original_value=value,
        normalized=value,
    )


def _run(text: str, dets: list[DetectedPII]) -> tuple[ProxyContext, str]:
    context = ProxyContext(raw_prompt=text)
    context.detected_entities = dets
    assess_risk(context)
    crypto = VaultCrypto(os.urandom(32))
    result = Tokenizer(InMemoryVaultStore(crypto), crypto, strict=True).anonymize(
        session_id=context.session_id,
        raw_prompt=text,
        detected_entities=context.detected_entities,
        policy_action=context.policy_action,
        entity_policies={
            (p.segment_id, p.start_idx, p.end_idx): p.action for p in context.entity_policies
        },
    )
    return context, result.anonymized_prompt


def _actions(context: ProxyContext) -> dict[str, str]:
    return {p.entity_type: p.action for p in context.entity_policies}


def test_low_risk_qi_kept_even_with_direct_identifier() -> None:
    text = "30대이고 연락처는 010-1234-5678 입니다."
    context, sent = _run(
        text,
        [
            _det(text, "30대", "AGE_GROUP", DetectionTier.RULE_ANCHORED),
            _det(text, "010-1234-5678", "PHONE_NUMBER", DetectionTier.RULE_ANCHORED),
        ],
    )
    # 요청 단위 값은 그대로(감사 로그·하위 호환)
    assert context.policy_action == "TOKENIZE"
    assert _actions(context) == {"AGE_GROUP": "ALLOW", "PHONE_NUMBER": "TOKENIZE"}
    assert sent == "30대이고 연락처는 【PHONE_1】 입니다."


def test_risky_qi_combination_generalized_not_tokenized() -> None:
    text = "35세이고 서울특별시 관악구 신림동 살아요. 010-1234-5678로 연락주세요."
    context, sent = _run(
        text,
        [
            _det(text, "35세", "AGE", DetectionTier.RULE_ANCHORED),
            _det(text, "신림동", "LOCATION", DetectionTier.MODEL),
            _det(text, "010-1234-5678", "PHONE_NUMBER", DetectionTier.RULE_ANCHORED),
        ],
    )
    actions = _actions(context)
    assert actions["PHONE_NUMBER"] == "TOKENIZE"
    assert actions["AGE"] == "GENERALIZE"
    assert actions["LOCATION"] == "GENERALIZE"
    assert "30대" in sent and "35세" not in sent
    assert "【PHONE_1】" in sent and "010-1234-5678" not in sent


def test_sensitive_always_tokenized() -> None:
    text = "제가 당뇨가 있어서 교환하고 싶어요."
    context, sent = _run(
        text, [_det(text, "당뇨", "SENSITIVE_HEALTH", DetectionTier.RULE_ANCHORED)]
    )
    assert _actions(context) == {"SENSITIVE_HEALTH": "TOKENIZE"}
    assert "당뇨" not in sent


def test_product_and_purchase_pattern_do_not_fail_l6() -> None:
    text = "매달 임신테스트기 주문하는 계정이에요. 010-9876-5432로 연락주세요."
    context, sent = _run(
        text,
        [
            _det(text, "매달", "PURCHASE_PATTERN", DetectionTier.RULE_ANCHORED),
            _det(text, "임신테스트기", "PRODUCT_ITEM", DetectionTier.RULE_ANCHORED),
            _det(text, "010-9876-5432", "PHONE_NUMBER", DetectionTier.RULE_ANCHORED),
        ],
    )
    # 변경
    assert _actions(context)["PRODUCT_ITEM"] == "GENERALIZE"
    assert _actions(context)["PURCHASE_PATTERN"] == "ALLOW"
    assert sent == "매달 【PRODUCT_1】 주문하는 계정이에요. 【PHONE_1】로 연락주세요."


def test_without_entity_policies_l6_keeps_old_behavior() -> None:
    text = "30대이고 연락처는 010-1234-5678 입니다."
    crypto = VaultCrypto(os.urandom(32))
    dets = [
        _det(text, "30대", "AGE_GROUP", DetectionTier.RULE_ANCHORED),
        _det(text, "010-1234-5678", "PHONE_NUMBER", DetectionTier.RULE_ANCHORED),
    ]
    result = Tokenizer(InMemoryVaultStore(crypto), crypto, strict=True).anonymize(
        session_id="s", raw_prompt=text, detected_entities=dets, policy_action="TOKENIZE"
    )
    assert result.anonymized_prompt == "【AGE_GROUP_1】이고 연락처는 【PHONE_1】 입니다."


@pytest.mark.parametrize("request_action", [None, "ALLOW", "GENERALIZE", "TOKENIZE"])
@pytest.mark.parametrize("item_action", [None, "ALLOW", "GENERALIZE", "TOKENIZE"])
def test_purchase_pattern_passes_through_all_policies(
    request_action: str | None, item_action: str | None
) -> None:
    text = "매달 정기배송"
    entity = _det(text, text, "PURCHASE_PATTERN", DetectionTier.RULE_ANCHORED)
    crypto = VaultCrypto(os.urandom(32))
    actions = (
        {(entity.segment_id, entity.start_idx, entity.end_idx): item_action}
        if item_action is not None
        else None
    )
    result = Tokenizer(InMemoryVaultStore(crypto), crypto, strict=True).anonymize(
        session_id="purchase-pattern-test",
        raw_prompt=text,
        detected_entities=[entity],
        policy_action=request_action,
        entity_policies=actions,
    )
    assert result.anonymized_prompt == text
    assert result.vault_mapping == {}
    assert result.token_types == {}


def test_high_risk_qis_keep_pattern_and_tokenize_order() -> None:
    text = "35세 신림동 매달 ORD-123"
    context, sent = _run(
        text,
        [
            _det(text, "35세", "AGE", DetectionTier.RULE_ANCHORED),
            _det(text, "신림동", "LOCATION", DetectionTier.MODEL),
            _det(text, "매달", "PURCHASE_PATTERN", DetectionTier.RULE_ANCHORED),
            _det(text, "ORD-123", "ORDER_ID", DetectionTier.RULE_ANCHORED),
        ],
    )
    assert context.policy_action == "TOKENIZE"
    assert _actions(context) == {
        "AGE": "GENERALIZE",
        "LOCATION": "GENERALIZE",
        "PURCHASE_PATTERN": "ALLOW",
        "ORDER_ID": "TOKENIZE",
    }
    pattern_policy = next(p for p in context.entity_policies if p.entity_type == "PURCHASE_PATTERN")
    assert pattern_policy.reason == "업무상 유지 정보(점수 반영)"
    assert "매달" in sent
    assert "35세" not in sent
    assert "ORD-123" not in sent
