import pytest

from privacy_proxy.models import DetectedPII as LegacyDetectedPII
from privacy_proxy.risk.entity_contract import (
    ENTITY_STATUS,
    L3_ENTITY_TYPES,
    L4_COMMERCE_ENTITY_TYPES,
    L4_NER_ENTITY_TYPES,
    L4_RECOGNIZER_ENTITY_TYPES,
    L4_SENSITIVE_ENTITY_TYPES,
    L5_SUPPORTED_ENTITY_TYPES,
    SCHEMA_ENTITY_TYPES,
)
from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class
from privacy_proxy.risk.weighted_score import calculate_weighted_risk
from privacy_proxy.schemas import DetectedPII, DetectionTier, EntityType


def test_shared_schema_inventory_is_complete_and_disjoint() -> None:
    assert {
        "PHONE_NUMBER",
        "EMAIL_ADDRESS",
        "KR_RRN",
        "KR_BRN",
        "PERSON_KO",
        "LOCATION_INFORMAL",
        "CUSTOMS_CLEARANCE_ID",
        "ORDER_ID",
        "TRACKING_NUMBER",
        "CUSTOMER_ID",
        "ACCOUNT_NUMBER",
        "ADDRESS_ROAD",
        "ADDRESS_LOT",
        "ADDRESS_DETAIL",
        "SENSITIVE_HEALTH",
        "SENSITIVE_SEX_LIFE",
        "PRODUCT_ITEM",
        "PURCHASE_PATTERN",
    } | L3_ENTITY_TYPES == SCHEMA_ENTITY_TYPES
    assert len(L3_ENTITY_TYPES) == 13
    assert len(L4_NER_ENTITY_TYPES) == 2
    assert len(L4_RECOGNIZER_ENTITY_TYPES) == 8
    assert len(L4_SENSITIVE_ENTITY_TYPES) == 2
    assert len(L4_COMMERCE_ENTITY_TYPES) == 2
    assert len(L5_SUPPORTED_ENTITY_TYPES) == 27
    assert len(SCHEMA_ENTITY_TYPES) == 27
    assert L5_SUPPORTED_ENTITY_TYPES == SCHEMA_ENTITY_TYPES
    assert set(ENTITY_STATUS) == SCHEMA_ENTITY_TYPES
    groups = [
        L3_ENTITY_TYPES,
        L4_COMMERCE_ENTITY_TYPES,
        L4_NER_ENTITY_TYPES,
        L4_RECOGNIZER_ENTITY_TYPES,
        L4_SENSITIVE_ENTITY_TYPES,
    ]
    assert sum(len(group) for group in groups) == len(set().union(*groups))


@pytest.mark.parametrize("entity_type", sorted(L5_SUPPORTED_ENTITY_TYPES))
def test_every_supported_entity_has_l5_classification_and_weight(entity_type: str) -> None:
    detection = DetectedPII(
        entity_type=entity_type,
        original_value="테스트",
        start_idx=0,
        end_idx=3,
        confidence=1.0,
        tier=DetectionTier.RULE_ANCHORED,
        source="CONTRACT_TEST",
    )

    assert privacy_class(detection) is not PrivacyClass.GENERAL
    assert calculate_weighted_risk([detection]).score >= 0.0


@pytest.mark.parametrize(
    "removed_type", ["ETC", "SENSITIVE_RELIGION", "SENSITIVE_FAMILY", "SENSITIVE_FINANCIAL"]
)
def test_removed_types_fail_closed(removed_type: str) -> None:
    from privacy_proxy.risk.score import assess_risk
    from privacy_proxy.schemas import ProxyContext

    assert removed_type not in SCHEMA_ENTITY_TYPES
    with pytest.raises(ValueError):
        EntityType(removed_type)
    detection = DetectedPII(
        entity_type=removed_type,
        original_value="기타",
        start_idx=0,
        end_idx=2,
        confidence=0.5,
        tier=DetectionTier.CANDIDATE,
    )

    assert privacy_class(detection) is PrivacyClass.GENERAL
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        calculate_weighted_risk([detection])
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(ProxyContext(raw_prompt="기타", detected_entities=[detection]))


def test_models_module_reexports_schema_ssot() -> None:
    assert LegacyDetectedPII is DetectedPII


def test_detection_serializes_exact_nine_field_contract() -> None:
    detection = DetectedPII(
        entity_type=EntityType.KR_BRN,
        original_value="123-45-67890",
        start_idx=0,
        end_idx=12,
        confidence=1.0,
        segment_id="seg-1",
        normalized="1234567890",
        tier=DetectionTier.RULE_ANCHORED,
        source="L3_BRN_RECOGNIZER",
    )

    payload = detection.model_dump(mode="json")

    assert set(payload) == {
        "entity_type",
        "original_value",
        "start_idx",
        "end_idx",
        "confidence",
        "segment_id",
        "normalized",
        "tier",
        "source",
    }
    assert payload["entity_type"] == "KR_BRN"
    assert payload["tier"] == "rule_anchored"


def test_detection_uses_common_schema_defaults() -> None:
    detection = DetectedPII(
        entity_type=EntityType.KR_RRN,
        original_value="000000-0000000",
        start_idx=0,
        end_idx=14,
        confidence=1.0,
        tier=DetectionTier.DETERMINISTIC,
    )

    assert detection.tier is DetectionTier.DETERMINISTIC
    assert detection.source == "unknown"
    assert detection.layer == "unknown"


@pytest.mark.parametrize("old_name", ["PHONE", "EMAIL", "RRN", "BUSINESS_REGISTRATION_NUMBER"])
def test_removed_names_are_not_silently_accepted(old_name: str) -> None:
    from privacy_proxy.risk.score import assess_risk
    from privacy_proxy.schemas import ProxyContext

    assert old_name not in SCHEMA_ENTITY_TYPES
    detection = DetectedPII(
        entity_type=old_name,
        original_value="test",
        start_idx=0,
        end_idx=4,
        confidence=None,
        tier=DetectionTier.RULE_ANCHORED,
    )
    with pytest.raises(ValueError, match="unsupported detected entity type"):
        assess_risk(ProxyContext(raw_prompt="test", detected_entities=[detection]))
