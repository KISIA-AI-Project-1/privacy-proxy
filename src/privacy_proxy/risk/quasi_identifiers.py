"""L5 classification and QI features for the shared EntityType contract."""

from dataclasses import dataclass
from enum import StrEnum

from privacy_proxy.risk.entity_contract import L5_SUPPORTED_ENTITY_TYPES
from privacy_proxy.schemas import DetectedPII, EntityType


class PrivacyClass(StrEnum):
    DIRECT = "DIRECT_IDENTIFIER"
    SERVICE = "SERVICE_IDENTIFIER"
    SENSITIVE = "SENSITIVE_INFORMATION"
    QI = "QUASI_IDENTIFIER"
    GENERAL = "GENERAL_INFORMATION"


@dataclass(frozen=True, slots=True)
class QIFeature:
    category: str
    deduplication_key: str
    specificity: int
    base_score: float
    reason: str
    detailed_location: bool = False


DIRECT_IDENTIFIERS = frozenset(
    {
        EntityType.PERSON_EN.value,
        EntityType.ADDRESS.value,
        EntityType.KR_RRN.value,
        EntityType.PHONE_NUMBER.value,
        EntityType.EMAIL_ADDRESS.value,
        EntityType.KR_PASSPORT.value,
        EntityType.KR_FRN.value,
        EntityType.KR_DRIVER_LICENSE.value,
        EntityType.PERSON_KO.value,
        EntityType.ACCOUNT_NUMBER.value,
        EntityType.ADDRESS_ROAD.value,
        EntityType.ADDRESS_LOT.value,
        EntityType.ADDRESS_DETAIL.value,
    }
)

SERVICE_IDENTIFIERS = frozenset(
    {
        EntityType.KR_BRN.value,
        EntityType.ORDER_ID.value,
        EntityType.CUSTOMER_ID.value,
        EntityType.TRACKING_NUMBER.value,
        EntityType.CUSTOMS_CLEARANCE_ID.value,
    }
)

SENSITIVE_INFORMATION = frozenset(
    {
        EntityType.SENSITIVE_HEALTH.value,
        EntityType.SENSITIVE_RELIGION.value,
        EntityType.SENSITIVE_FAMILY.value,
        EntityType.SENSITIVE_FINANCIAL.value,
    }
)

QUASI_IDENTIFIERS = frozenset(
    {
        EntityType.LOCATION_INFORMAL.value,
        EntityType.LOCATION.value,
        EntityType.AGE.value,
        EntityType.AGE_GROUP.value,
        EntityType.DATE_OF_BIRTH.value,
    }
)


def canonical_entity_type(entity: DetectedPII) -> str:
    """Return the exact producer value without repairing unknown spellings."""
    if isinstance(entity.entity_type, EntityType):
        return entity.entity_type.value
    return entity.entity_type


def privacy_class(entity: DetectedPII) -> PrivacyClass:
    entity_type = canonical_entity_type(entity)
    if entity_type not in L5_SUPPORTED_ENTITY_TYPES:
        return PrivacyClass.GENERAL
    if entity_type in DIRECT_IDENTIFIERS:
        return PrivacyClass.DIRECT
    if entity_type in SERVICE_IDENTIFIERS:
        return PrivacyClass.SERVICE
    if entity_type in SENSITIVE_INFORMATION:
        return PrivacyClass.SENSITIVE
    if entity_type in QUASI_IDENTIFIERS:
        return PrivacyClass.QI
    return PrivacyClass.GENERAL


def location_level(value: str) -> str:
    compact = "".join(value.split())
    if compact.endswith(("특별자치도", "특별자치시", "특별시", "광역시", "도")):
        return "PROVINCE"
    if compact.endswith(("읍", "면", "동", "리", "가")):
        return "NEIGHBORHOOD"
    if compact.endswith(("시", "군", "구")):
        return "DISTRICT"
    return "UNKNOWN"


def to_qi_feature(entity: DetectedPII) -> QIFeature | None:
    """Convert a supported QI entity into an internal L5 feature."""
    if canonical_entity_type(entity) not in QUASI_IDENTIFIERS:
        return None

    entity_type = canonical_entity_type(entity)
    # Age, age group and birth date describe the same demographic dimension.
    # Keep the most specific signal instead of counting them independently.
    if entity_type == EntityType.DATE_OF_BIRTH:
        return QIFeature("AGE", "AGE", 3, 22.0, "생년월일 정보가 포함됨")
    if entity_type == EntityType.AGE:
        return QIFeature("AGE", "AGE", 2, 20.0, "정확한 연령이 포함됨")
    if entity_type == EntityType.AGE_GROUP:
        return QIFeature("AGE", "AGE", 1, 8.0, "연령대 정보가 포함됨")

    value = entity.original_value.strip()
    level = location_level(value)
    score, specificity, label = {
        "PROVINCE": (5.0, 1, "시·도 수준의 지역이 포함됨"),
        "DISTRICT": (15.0, 2, "시·군·구 수준의 지역이 포함됨"),
        "NEIGHBORHOOD": (22.0, 3, "읍·면·동 수준의 지역이 포함됨"),
        "UNKNOWN": (5.0, 0, "상세도를 확인할 수 없는 지역이 포함됨"),
    }[level]
    normalized_value = "".join(value.split()).casefold()
    return QIFeature(
        category="LOCATION",
        deduplication_key=f"LOCATION:{normalized_value}",
        specificity=specificity,
        base_score=score,
        reason=label,
        detailed_location=level in {"DISTRICT", "NEIGHBORHOOD"},
    )
