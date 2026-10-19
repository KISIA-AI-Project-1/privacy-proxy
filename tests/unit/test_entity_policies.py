"""Item policy and purchase-pattern retention regressions."""

import pytest

from privacy_proxy.risk.score import PURCHASE_PATTERN_RETENTION_REASON, assess_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def context_for(entities: list[tuple[str, str]]) -> ProxyContext:
    text = " ".join(value for _, value in entities)
    detected = []
    start = 0
    for kind, value in entities:
        detected.append(
            DetectedPII(
                entity_type=kind,
                original_value=value,
                start_idx=start,
                end_idx=start + len(value),
                confidence=None,
                tier=DetectionTier.RULE_ANCHORED,
                source="test",
            )
        )
        start += len(value) + 1
    return ProxyContext(raw_prompt=text, detected_entities=detected)


@pytest.mark.parametrize(
    ("extra", "score", "request_action"),
    [
        ([], 12, "ALLOW"),
        ([("LOCATION", "강남구")], 35, "GENERALIZE"),
        ([("AGE", "30세"), ("LOCATION", "강남구")], 59, "GENERALIZE"),
        ([("AGE", "30세"), ("LOCATION", "신림동")], 66, "GENERALIZE"),
        ([("PHONE_NUMBER", "010-1234-5678")], 80, "TOKENIZE"),
        ([("ORDER_ID", "ORD-123")], 85, "TOKENIZE"),
        ([("SENSITIVE_HEALTH", "당뇨")], 80, "TOKENIZE"),
    ],
)
def test_pattern_kept_regardless_of_request_policy(
    extra: list[tuple[str, str]], score: float, request_action: str
) -> None:
    context = assess_risk(context_for([("PURCHASE_PATTERN", "매달 정기배송"), *extra]))
    assert context.risk_score == score
    assert context.policy_action == request_action
    policy = context.entity_policies[0]
    assert policy.action == "ALLOW"
    assert policy.reason == "업무상 유지 정보(점수 반영)"
    assert policy.privacy_class == "QUASI_IDENTIFIER"
    assert "매달 정기배송" not in policy.model_dump_json()
    assert context.risk_reasons.count(PURCHASE_PATTERN_RETENTION_REASON) == 1


def test_retention_notice_only_when_pattern_detected() -> None:
    context = assess_risk(context_for([("PRODUCT_ITEM", "머그컵")]))
    assert PURCHASE_PATTERN_RETENTION_REASON not in context.risk_reasons
    assert context.entity_policies[0].action == "GENERALIZE"
    assert (
        context.entity_policies[0].reason == "상품명 보호: '상품'으로 비가역 일반화 요청(복원 제외)"
    )


@pytest.mark.parametrize(
    "extra",
    [[], [("AGE", "30세"), ("LOCATION", "신림동")], [("PHONE_NUMBER", "010-1234-5678")]],
)
def test_product_generalization_is_a_request_without_changing_raw_text(
    extra: list[tuple[str, str]],
) -> None:
    context = context_for([("PRODUCT_ITEM", "가상테스트기"), *extra])
    original = context.raw_prompt
    assess_risk(context)
    product = next(p for p in context.entity_policies if p.entity_type == "PRODUCT_ITEM")
    assert product.action == "GENERALIZE"
    assert "비가역 일반화 요청" in product.reason
    assert "복원 제외" in product.reason
    assert "가상테스트기" not in product.reason
    assert context.raw_prompt == original
    assert context.anonymized_prompt is None
    assert context.vault_mapping == {}


@pytest.mark.parametrize("kind", ["ADDRESS", "ORDER_ID", "SENSITIVE_HEALTH", "PHONE_NUMBER"])
def test_protected_items_ignore_qi_threshold(kind: str) -> None:
    context = assess_risk(context_for([("AGE_GROUP", "30대"), (kind, "테스트")]))
    assert [policy.action for policy in context.entity_policies] == ["ALLOW", "TOKENIZE"]


def test_high_qi_score_generalizes_product_but_keeps_pattern() -> None:
    context = assess_risk(
        context_for([("PRODUCT_ITEM", "머그컵"), ("PURCHASE_PATTERN", "매달"), ("AGE", "30세")])
    )
    assert context.risk_score == 40
    assert [policy.action for policy in context.entity_policies] == [
        "GENERALIZE",
        "ALLOW",
        "GENERALIZE",
    ]
    assert "머그컵" not in context.entity_policies[0].reason


def test_reassessment_replaces_policies_and_retention_notice() -> None:
    context = assess_risk(context_for([("PURCHASE_PATTERN", "매달")]))
    context.detected_entities = []
    assess_risk(context)
    assert context.entity_policies == []
    assert context.risk_reasons == []
