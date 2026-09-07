from collections.abc import Iterable

import pytest
from privacy_proxy.models import DetectedPII, ProxyContext

from privacy_proxy.risk.quasi_identifiers import (
    PrivacyClass,
    privacy_class,
    to_qi_feature,
)
from privacy_proxy.risk.score import assess_risk


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
                layer="L3",
            )
        )
        cursor = end
    return ProxyContext(raw_prompt=text, detected_entities=detected)


@pytest.mark.parametrize(
    ("text", "entities", "expected_score", "expected_level"),
    [
        (
            "30대이고 서울특별시에 거주합니다.",
            [("AGE_GROUP", "30대"), ("LOCATION_INFORMAL", "서울특별시")],
            21.0,
            "LOW",
        ),
        (
            "30대이고 영통구에 거주합니다.",
            [("AGE_GROUP", "30대"), ("LOCATION_INFORMAL", "영통구")],
            31.0,
            "MEDIUM",
        ),
        (
            "37세이고 서울특별시에 거주합니다.",
            [("AGE", "37세"), ("LOCATION_INFORMAL", "서울특별시")],
            33.0,
            "MEDIUM",
        ),
        (
            "37세이고 영통구에 거주합니다.",
            [("AGE", "37세"), ("LOCATION_INFORMAL", "영통구")],
            60.0,
            "HIGH",
        ),
        (
            "37세이고 매탄동에 거주합니다.",
            [("AGE", "37세"), ("LOCATION_INFORMAL", "매탄동")],
            67.0,
            "HIGH",
        ),
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


def test_age_location_and_rare_product_score() -> None:
    text = "영통구에 거주하는 37세 고객이 한정판 상품을 구매했습니다."
    result = assess_risk(
        context_for(
            text,
            [
                ("LOCATION_INFORMAL", "영통구"),
                ("AGE", "37세"),
                ("PRODUCT_NAME", "한정판 상품"),
            ],
        )
    )
    assert result.risk_score == 82.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "GENERALIZE"
    assert "희귀 상품과 세부 지역이 결합됨" in result.risk_reasons


def test_time_and_detailed_location_combination() -> None:
    text = "영통구에서 2026-09-07 14:30에 구매했습니다."
    result = assess_risk(
        context_for(
            text,
            [
                ("LOCATION_INFORMAL", "영통구"),
                ("PURCHASE_TIME", "2026-09-07 14:30"),
            ],
        )
    )
    assert result.risk_score == 43.0
    assert "정확한 시각과 세부 지역이 결합됨" in result.risk_reasons


def test_rare_product_and_detailed_location_combination() -> None:
    text = "영통구에서 한정판 운동화를 구매했습니다."
    result = assess_risk(
        context_for(
            text,
            [
                ("LOCATION_INFORMAL", "영통구"),
                ("PURCHASED_PRODUCT", "한정판 운동화"),
            ],
        )
    )
    assert result.risk_score == 41.0
    assert "희귀 상품과 세부 지역이 결합됨" in result.risk_reasons


@pytest.mark.parametrize(
    "entity_type",
    [
        "AGE",
        "AGE_GROUP",
        "GENDER",
        "PRODUCT",
        "PRODUCT_NAME",
        "PURCHASED_PRODUCT",
        "DATE_TIME",
        "DATETIME",
        "PURCHASE_TIME",
        "ORDER_TIME",
        "PRICE",
        "AMOUNT",
        "REFUND_REASON",
        "PURCHASE_COUNT",
    ],
)
def test_l4_pending_entity_is_classified_as_qi(entity_type: str) -> None:
    entity = DetectedPII(
        entity_type=entity_type,
        original_value="테스트",
        start_idx=0,
        end_idx=3,
        layer="L4",
    )
    assert privacy_class(entity) is PrivacyClass.QI
    assert to_qi_feature(entity) is not None


@pytest.mark.parametrize(
    ("entity_type", "value", "expected_score"),
    [
        ("GENDER", "여성", 5.0),
        ("PRICE", "39,000원", 8.0),
        ("AMOUNT", "39,000원", 8.0),
        ("REFUND_REASON", "상품 파손", 10.0),
        ("PURCHASE_COUNT", "3회", 6.0),
    ],
)
def test_l4_pending_scalar_qi_scores(entity_type: str, value: str, expected_score: float) -> None:
    result = assess_risk(context_for(value, [(entity_type, value)]))
    assert result.risk_score == expected_score


def test_common_product_is_not_marked_rare() -> None:
    entity = DetectedPII(
        entity_type="PRODUCT",
        original_value="운동화",
        start_idx=0,
        end_idx=3,
        layer="L4",
    )
    feature = to_qi_feature(entity)
    assert feature is not None
    assert feature.base_score == 5.0
    assert feature.rare is False


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
        layer="L4",
    )
    result = assess_risk(
        ProxyContext(raw_prompt=text, detected_entities=[duplicate, duplicate.model_copy()])
    )
    assert result.risk_score == 15.0
    assert "서로 다른 준식별자 2개가 결합됨" not in result.risk_reasons


def test_different_location_roles_are_preserved() -> None:
    text = "서울특별시에 살고 영통구에서 근무합니다."
    result = assess_risk(
        context_for(
            text,
            [("RESIDENCE_LOCATION", "서울특별시"), ("WORKPLACE_LOCATION", "영통구")],
        )
    )
    assert result.risk_score == 28.0


def test_unique_identifier_has_priority() -> None:
    text = "주문번호 ORD-2026-001을 확인해줘."
    result = assess_risk(context_for(text, [("ORDER_ID", "ORD-2026-001")]))
    assert result.risk_score == 85.0
    assert result.risk_level == "HIGH"
    assert result.policy_action == "TOKENIZE"


@pytest.mark.parametrize(
    ("entity_type", "expected_class"),
    [
        ("PERSON", PrivacyClass.DIRECT),
        ("ADDRESS_TAIL", PrivacyClass.DIRECT),
        ("LOCATION_INFORMAL", PrivacyClass.QI),
        ("ORDER_ID", PrivacyClass.UNIQUE),
        ("TRACKING_NUMBER", PrivacyClass.UNIQUE),
        ("CUSTOMS_CLEARANCE_ID", PrivacyClass.UNIQUE),
        ("CUSTOMER_ID", PrivacyClass.UNIQUE),
        ("SENSITIVE_HEALTH", PrivacyClass.SENSITIVE),
        ("SENSITIVE_RELIGION", PrivacyClass.SENSITIVE),
        ("SENSITIVE_FAMILY", PrivacyClass.SENSITIVE),
        ("SENSITIVE_FINANCIAL", PrivacyClass.SENSITIVE),
    ],
)
def test_confirmed_l4_entity_contract(entity_type: str, expected_class: PrivacyClass) -> None:
    entity = DetectedPII(
        entity_type=entity_type,
        original_value="테스트",
        start_idx=0,
        end_idx=3,
        layer="L4",
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
def test_sensitive_candidate_uses_confidence(
    confidence: float,
    expected_score: float,
    expected_level: str,
    expected_action: str,
) -> None:
    entity = DetectedPII(
        entity_type="SENSITIVE_HEALTH",
        original_value="아토피",
        start_idx=0,
        end_idx=3,
        layer="L4",
        confidence=confidence,
    )
    result = assess_risk(ProxyContext(raw_prompt="아토피가 있어요.", detected_entities=[entity]))
    assert result.risk_score == expected_score
    assert result.risk_level == expected_level
    assert result.policy_action == expected_action
    assert f"confidence={confidence:.2f}" in result.risk_reasons[0]


def test_raw_prompt_is_excluded_from_serialization() -> None:
    context = ProxyContext(raw_prompt="비공개 원문")
    assert "raw_prompt" not in context.model_dump()


def test_invalid_span_is_rejected_before_scoring() -> None:
    context = ProxyContext(
        raw_prompt="홍길동",
        detected_entities=[
            DetectedPII(
                entity_type="PERSON",
                original_value="김철수",
                start_idx=0,
                end_idx=3,
                layer="L3",
            )
        ],
    )
    with pytest.raises(ValueError, match="span mismatch"):
        assess_risk(context)
