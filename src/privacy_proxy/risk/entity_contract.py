"""L5 entity allowlist derived from the shared schema EntityType enum."""

from enum import StrEnum

from privacy_proxy.schemas import EntityType


class EntityStatus(StrEnum):
    EMITTED = "emitted"
    ADAPTER_PENDING = "adapter_pending"
    IMPLEMENTATION_PENDING = "implementation_pending"
    EXCLUDED = "excluded"


L3_ENTITY_TYPES = frozenset(
    {
        EntityType.PHONE.value,
        EntityType.EMAIL.value,
        EntityType.RRN.value,
        EntityType.BUSINESS_REGISTRATION_NUMBER.value,
    }
)

L4_NER_ENTITY_TYPES = frozenset(
    {
        EntityType.PERSON_KO.value,
        EntityType.LOCATION_INFORMAL.value,
    }
)

L4_RECOGNIZER_ENTITY_TYPES = frozenset(
    {
        EntityType.CUSTOMS_CLEARANCE_ID.value,
        EntityType.ORDER_ID.value,
        EntityType.TRACKING_NUMBER.value,
        EntityType.CUSTOMER_ID.value,
        EntityType.ACCOUNT_NUMBER.value,
        EntityType.ADDRESS_ROAD.value,
        EntityType.ADDRESS_LOT.value,
        EntityType.ADDRESS_DETAIL.value,
    }
)

L4_SENSITIVE_ENTITY_TYPES = frozenset(
    {
        EntityType.SENSITIVE_HEALTH.value,
        EntityType.SENSITIVE_RELIGION.value,
        EntityType.SENSITIVE_FAMILY.value,
        EntityType.SENSITIVE_FINANCIAL.value,
    }
)

L5_SUPPORTED_ENTITY_TYPES = frozenset(
    L3_ENTITY_TYPES | L4_NER_ENTITY_TYPES | L4_RECOGNIZER_ENTITY_TYPES | L4_SENSITIVE_ENTITY_TYPES
)
SCHEMA_ENTITY_TYPES = frozenset(entity_type.value for entity_type in EntityType)

ENTITY_STATUS: dict[str, EntityStatus] = {
    **dict.fromkeys(L3_ENTITY_TYPES, EntityStatus.EMITTED),
    **dict.fromkeys(L4_RECOGNIZER_ENTITY_TYPES, EntityStatus.EMITTED),
    **dict.fromkeys(L4_NER_ENTITY_TYPES, EntityStatus.ADAPTER_PENDING),
    **dict.fromkeys(L4_SENSITIVE_ENTITY_TYPES, EntityStatus.IMPLEMENTATION_PENDING),
    EntityType.ETC.value: EntityStatus.EXCLUDED,
}
