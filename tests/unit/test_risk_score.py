from collections.abc import Iterable

import pytest

from privacy_proxy.risk.quasi_identifiers import (
    PrivacyClass,
    privacy_class,
)
from privacy_proxy.risk.score import assess_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def context_for(text: str, entities: Iterable[tuple[str, str]]) -> ProxyContext:
    detected: list[DetectedPII] = []
    cursor = 0
    for entity_type, value in entities:
        start = text.index(value, cursor)
        end = start + len(value)
        detected.append(
            DetectedPII(
                entity_type=entity_type,
                original_value=value,
                start_idx=start,
                end_idx=end,
                confidence=1.0,
                tier=DetectionTier.DETERMINISTIC,
                source="L3_TEST",
            )
        )
        cursor = end
    return ProxyContext(raw_prompt=text, detected_entities=detected)


@pytest.mark.parametrize(
    ("text", "entities", "expected_score", "expected_level"),
    [
        (
            "서울특별시에 거주합니다.",
            [("LOCATION_INFORMAL", "서울특별시")],
            5.0,
            "LOW",
        ),
        (
            "영통구에 거주합니다.",
            [("LOCATION_INFORMAL", "영통구")],
            15.0,
            "LOW",
        ),
        (
            "매탄동에 거주합니다.",
            [("LOCATION_INFORMAL", "매탄동")],
            22.0,
            "LOW",
        ),
    ],
)
def test_boundary_examples(
    text: str,
    entities: list[tuple[str, str]],
    expected_score: float,
    expected_level: str,
) -> None:
    result = assess_risk(context_for(text, entities))
    assert result.risk_score == expected_score
    assert result.risk_level == expected_level


def test_noncanonical_entity_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(context_for("테스트", [("UNKNOWN_ENTITY", "테스트")]))


def test_etc_fails_closed_in_operational_score() -> None:
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(context_for("기타", [("ETC", "기타")]))


@pytest.mark.parametrize("entity_type", ["order_id", " ORDER_ID", "ORDER_ID "])
def test_noncanonical_spelling_fails_closed(entity_type: str) -> None:
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(context_for("테스트", [(entity_type, "테스트")]))


def test_noncanonical_overlap_cannot_be_removed_before_validation() -> None:
    text = "ORD-2026-001"
    canonical = DetectedPII(
        entity_type="ORDER_ID",
        original_value=text,
        start_idx=0,
        end_idx=len(text),
        confidence=1.0,
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_ORDER_TEST",
    )
    noncanonical = canonical.model_copy(update={"entity_type": "UNKNOWN_ENTITY"})

    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(ProxyContext(raw_prompt=text, detected_entities=[canonical, noncanonical]))


def test_distinct_locations_without_verified_hierarchy_are_preserved() -> None:
    text = "서울특별시에서 영통구로 갑니다."
    result = assess_risk(
        context_for(
            text,
            [
                ("LOCATION_INFORMAL", "서울특별시"),
                ("LOCATION_INFORMAL", "영통구"),
            ],
        )
    )
    assert result.risk_score == 28.0
    assert "서로 다른 준식별자 2개가 결합됨" in result.risk_reasons


def test_identical_location_is_counted_once() -> None:
    text = "영통구에 가요."
    duplicate = DetectedPII(
        entity_type="LOCATION_INFORMAL",
        original_value="영통구",
        start_idx=0,
        end_idx=3,
        confidence=1.0,
        tier=DetectionTier.MODEL,
        source="L4_TEST",
    )
    result = assess_risk(
        ProxyContext(raw_prompt=text, detected_entities=[duplicate, duplicate.model_copy()])
    )
    assert result.risk_score == 15.0
    assert "서로 다른 준식별자 2개가 결합됨" not in result.risk_reasons


def test_service_identifier_has_priority() -> None:
    text = "주문번호 ORD-2026-001을 확인해줘."
    result = assess_risk(context_for(text, [("ORDER_ID", "ORD-2026-001")]))
    assert result.risk_score == 85.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "TOKENIZE"


@pytest.mark.parametrize(
    ("entity_type", "expected_class"),
    [
        ("PERSON_KO", PrivacyClass.DIRECT),
        ("ADDRESS_ROAD", PrivacyClass.DIRECT),
        ("LOCATION_INFORMAL", PrivacyClass.QI),
        ("ORDER_ID", PrivacyClass.SERVICE),
        ("TRACKING_NUMBER", PrivacyClass.SERVICE),
        ("CUSTOMS_CLEARANCE_ID", PrivacyClass.SERVICE),
        ("CUSTOMER_ID", PrivacyClass.SERVICE),
        ("SENSITIVE_HEALTH", PrivacyClass.SENSITIVE),
        ("SENSITIVE_SEX_LIFE", PrivacyClass.SENSITIVE),
        ("PRODUCT_ITEM", PrivacyClass.QI),
        ("PURCHASE_PATTERN", PrivacyClass.QI),
    ],
)
def test_confirmed_l4_entity_contract(entity_type: str, expected_class: PrivacyClass) -> None:
    entity = DetectedPII(
        entity_type=entity_type,
        original_value="테스트",
        start_idx=0,
        end_idx=3,
        confidence=1.0,
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_TEST",
    )
    assert privacy_class(entity) is expected_class


@pytest.mark.parametrize(
    ("confidence", "expected_score", "expected_level", "expected_action"),
    [
        (0.3, 24.0, "LOW", "TOKENIZE"),
        (0.4, 32.0, "MEDIUM", "TOKENIZE"),
        (0.5, 40.0, "MEDIUM", "TOKENIZE"),
        (1.0, 80.0, "HIGH", "TOKENIZE"),
    ],
)
@pytest.mark.parametrize("entity_type", ["SENSITIVE_HEALTH", "SENSITIVE_SEX_LIFE"])
def test_sensitive_candidate_uses_confidence(
    entity_type: str,
    confidence: float,
    expected_score: float,
    expected_level: str,
    expected_action: str,
) -> None:
    entity = DetectedPII(
        entity_type=entity_type,
        original_value="아토피",
        start_idx=0,
        end_idx=3,
        confidence=confidence,
        tier=DetectionTier.CANDIDATE,
        source="L4_SENSITIVE_TEST",
    )
    result = assess_risk(ProxyContext(raw_prompt="아토피가 있어요.", detected_entities=[entity]))
    assert result.risk_score == expected_score
    assert result.risk_level == expected_level
    assert result.policy_action == expected_action
    assert f"confidence={confidence:.2f}" in result.risk_reasons[0]


def test_raw_prompt_is_excluded_from_serialization() -> None:
    context = ProxyContext(
        raw_prompt="비공개 원문",
        llm_raw_response={"private": "raw"},
        final_response={"private": "final"},
        final_response_log="private-log",
    )
    payload = context.model_dump()
    assert "raw_prompt" not in payload
    assert "llm_raw_response" not in payload
    assert "final_response" not in payload
    assert "final_response_log" not in payload


def test_invalid_span_is_rejected_before_scoring() -> None:
    context = ProxyContext(
        raw_prompt="홍길동",
        detected_entities=[
            DetectedPII(
                entity_type="PERSON_KO",
                original_value="김철수",
                start_idx=0,
                end_idx=3,
                confidence=1.0,
                tier=DetectionTier.MODEL,
                source="L3_TEST",
            )
        ],
    )
    with pytest.raises(ValueError, match="span mismatch"):
        assess_risk(context)


@pytest.mark.parametrize(
    "entity_type",
    [
        "PERSON_KO",
        "PHONE_NUMBER",
        "EMAIL_ADDRESS",
        "KR_RRN",
        "ACCOUNT_NUMBER",
        "ADDRESS_ROAD",
        "ADDRESS_LOT",
        "ADDRESS_DETAIL",
    ],
)
def test_new_direct_identifier_contract_is_tokenized(entity_type: str) -> None:
    result = assess_risk(context_for("테스트", [(entity_type, "테스트")]))

    assert result.risk_score == 80.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "TOKENIZE"


def test_business_registration_number_is_protected_as_service_identifier() -> None:
    result = assess_risk(
        context_for(
            "123-45-67890",
            [("KR_BRN", "123-45-67890")],
        )
    )

    assert result.risk_score == 85.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "TOKENIZE"


def test_unknown_detected_entity_fails_closed() -> None:
    context = context_for("비밀값", [("UNREGISTERED_PRIVATE_VALUE", "비밀값")])

    with pytest.raises(ValueError, match="unsupported detected entity type") as exc_info:
        assess_risk(context)
    assert "UNREGISTERED_PRIVATE_VALUE" not in str(exc_info.value)
    assert "비밀값" not in str(exc_info.value)


@pytest.mark.parametrize(
    "entities,score,action",
    [
        ([("PRODUCT_ITEM", "머그컵")], 5, "ALLOW"),
        ([("PURCHASE_PATTERN", "매주 구매")], 12, "ALLOW"),
        ([("PRODUCT_ITEM", "머그컵"), ("PRODUCT_ITEM", "접시")], 5, "ALLOW"),
        ([("PRODUCT_ITEM", "머그컵"), ("PURCHASE_PATTERN", "매주 구매")], 12, "ALLOW"),
        ([("PURCHASE_PATTERN", "매주 구매"), ("PRODUCT_ITEM", "머그컵")], 12, "ALLOW"),
        ([("AGE", "30세"), ("PRODUCT_ITEM", "머그컵")], 33, "GENERALIZE"),
        ([("LOCATION", "강남구"), ("PURCHASE_PATTERN", "매주 구매")], 35, "GENERALIZE"),
        (
            [("AGE", "30세"), ("LOCATION", "강남구"), ("PURCHASE_PATTERN", "매주 구매")],
            59,
            "GENERALIZE",
        ),
        ([("ORDER_ID", "ORD-001"), ("PRODUCT_ITEM", "머그컵")], 85, "TOKENIZE"),
        ([("SENSITIVE_SEX_LIFE", "민감내용"), ("PRODUCT_ITEM", "머그컵")], 80, "TOKENIZE"),
    ],
)
def test_commerce_policy_and_combination(
    entities: list[tuple[str, str]], score: float, action: str
) -> None:
    text = " / ".join(value for _, value in entities)
    result = assess_risk(context_for(text, entities))
    assert result.risk_score == score
    assert result.policy_action == action
    assert all(value not in " ".join(result.risk_reasons) for _, value in entities)
