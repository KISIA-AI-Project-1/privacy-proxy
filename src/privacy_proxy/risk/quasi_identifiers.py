"""L5 entity classification and initial identifying-power weights.

The weights are experimental policy values, not legal thresholds. Keeping them in
one module makes later calibration against population statistics straightforward.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from privacy_proxy.models import DetectedPII


class PrivacyClass(StrEnum):
    DIRECT = "DIRECT_IDENTIFIER"
    SERVICE = "SERVICE_IDENTIFIER"
    SENSITIVE = "SENSITIVE_INFORMATION"
    QI = "QUASI_IDENTIFIER"
    GENERAL = "GENERAL_INFORMATION"


class Rarity(StrEnum):
    COMMON = "COMMON"
    MODERATE = "MODERATE"
    RARE = "RARE"
    VERY_RARE = "VERY_RARE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class QIFeature:
    category: str
    deduplication_key: str
    specificity: int
    base_score: float
    reason: str
    exact_age: bool = False
    detailed_location: bool = False
    rare: bool = False


DIRECT_IDENTIFIERS = frozenset(
    {
        "PERSON",
        "NAME",
        "PHONE_NUMBER",
        "EMAIL_ADDRESS",
        "EMAIL",
        "ADDRESS",
        "STREET_ADDRESS",
        "ADDRESS_TAIL",
        "CREDIT_CARD",
        "IP_ADDRESS",
        "KR_RRN",
        "RESIDENT_REGISTRATION_NUMBER",
        "PASSPORT_NUMBER",
        "DRIVER_LICENSE_NUMBER",
    }
)

SERVICE_IDENTIFIERS = frozenset(
    {
        "ORDER_NUMBER",
        "ORDER_ID",
        "CUSTOMER_NUMBER",
        "CUSTOMER_ID",
        "MEMBER_NUMBER",
        "MEMBER_ID",
        "TRACKING_NUMBER",
        "INVOICE_NUMBER",
        "PERSONAL_CUSTOMS_CODE",
        "CUSTOMS_CLEARANCE_ID",
    }
)

SENSITIVE_INFORMATION = frozenset(
    {
        "SENSITIVE_HEALTH",
        "SENSITIVE_RELIGION",
        "SENSITIVE_FAMILY",
        "SENSITIVE_FINANCIAL",
    }
)

_LOCATION_TYPES = frozenset(
    {
        "LOCATION",
        "LOCATION_INFORMAL",
        "RESIDENCE_LOCATION",
        "WORKPLACE_LOCATION",
        "SHIPPING_LOCATION",
    }
)
_AGE_TYPES = frozenset({"AGE", "AGE_GROUP"})
_TIME_TYPES = frozenset({"DATE_TIME", "DATETIME", "PURCHASE_TIME", "ORDER_TIME"})
_PRODUCT_TYPES = frozenset({"PRODUCT", "PRODUCT_NAME", "PURCHASED_PRODUCT"})
_OTHER_QI_SCORES: dict[str, tuple[float, str]] = {
    "GENDER": (5.0, "성별 정보가 포함됨"),
    "PRICE": (8.0, "구매 금액 정보가 포함됨"),
    "AMOUNT": (8.0, "금액 정보가 포함됨"),
    "REFUND_REASON": (10.0, "환불 사유가 포함됨"),
    "PURCHASE_COUNT": (6.0, "구매 횟수 정보가 포함됨"),
}

_EXACT_AGE_RE = re.compile(r"^(?:만\s*)?\d{1,3}\s*세$")
_RARE_PRODUCT_RE = re.compile(r"한정판|희귀|리미티드|limited|단종", re.IGNORECASE)


def normalized_entity_type(entity: DetectedPII) -> str:
    return entity.entity_type.strip().upper()


def privacy_class(entity: DetectedPII) -> PrivacyClass:
    entity_type = normalized_entity_type(entity)
    if entity_type in DIRECT_IDENTIFIERS:
        return PrivacyClass.DIRECT
    if entity_type in SERVICE_IDENTIFIERS:
        return PrivacyClass.SERVICE
    if entity_type in SENSITIVE_INFORMATION:
        return PrivacyClass.SENSITIVE
    if (
        entity_type in _LOCATION_TYPES
        or entity_type in _AGE_TYPES
        or entity_type in _TIME_TYPES
        or entity_type in _PRODUCT_TYPES
        or entity_type in _OTHER_QI_SCORES
    ):
        return PrivacyClass.QI
    return PrivacyClass.GENERAL


def location_level(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if re.search(r"(?:특별자치도|특별자치시|특별시|광역시|도)$", compact):
        return "PROVINCE"
    if re.search(r"(?:읍|면|동|리|가)$", compact):
        return "NEIGHBORHOOD"
    if re.search(r"(?:시|군|구)$", compact):
        return "DISTRICT"
    return "UNKNOWN"


def _location_role(entity_type: str) -> str:
    if entity_type == "RESIDENCE_LOCATION":
        return "RESIDENCE"
    if entity_type == "WORKPLACE_LOCATION":
        return "WORKPLACE"
    if entity_type == "SHIPPING_LOCATION":
        return "SHIPPING"
    return "UNSPECIFIED"


def to_qi_feature(entity: DetectedPII) -> QIFeature | None:
    """Convert an L3/L4 entity into an internal L5 QI feature."""
    entity_type = normalized_entity_type(entity)
    value = entity.original_value.strip()

    if entity_type in _LOCATION_TYPES:
        level = location_level(value)
        score, specificity, label = {
            "PROVINCE": (5.0, 1, "시·도 수준의 지역이 포함됨"),
            "DISTRICT": (15.0, 2, "시·군·구 수준의 지역이 포함됨"),
            "NEIGHBORHOOD": (22.0, 3, "읍·면·동 수준의 지역이 포함됨"),
            "UNKNOWN": (5.0, 0, "상세도를 확인할 수 없는 지역이 포함됨"),
        }[level]
        role = _location_role(entity_type)
        normalized_value = re.sub(r"\s+", "", value).casefold()
        return QIFeature(
            category="LOCATION",
            # Until a location normalizer verifies an administrative hierarchy,
            # only identical location values are safe to de-duplicate. Grouping
            # every value by role alone incorrectly collapses unrelated places.
            deduplication_key=f"LOCATION:{role}:{normalized_value}",
            specificity=specificity,
            base_score=score,
            reason=label,
            detailed_location=level in {"DISTRICT", "NEIGHBORHOOD"},
        )

    if entity_type in _AGE_TYPES:
        exact = entity_type == "AGE" and bool(_EXACT_AGE_RE.fullmatch(value))
        if exact:
            return QIFeature("AGE", "AGE", 2, 20.0, "정확한 연령이 포함됨", exact_age=True)
        return QIFeature("AGE", "AGE", 1, 8.0, "연령대 정보가 포함됨")

    if entity_type in _PRODUCT_TYPES:
        rare = bool(_RARE_PRODUCT_RE.search(value))
        if rare:
            return QIFeature(
                "PRODUCT",
                "PRODUCT",
                2,
                18.0,
                "희귀·한정판 상품 정보가 포함됨",
                rare=True,
            )
        return QIFeature("PRODUCT", "PRODUCT", 1, 5.0, "상품 정보가 포함됨")

    if entity_type in _TIME_TYPES:
        return QIFeature("TIME", "TIME", 1, 12.0, "정확한 날짜·시간 정보가 포함됨")

    other = _OTHER_QI_SCORES.get(entity_type)
    if other is not None:
        score, reason = other
        return QIFeature(entity_type, entity_type, 1, score, reason)
    return None
