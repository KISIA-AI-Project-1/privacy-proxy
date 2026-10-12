"""Canonical data contracts shared by the L1-L9 pipeline."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityType(StrEnum):
    """Entity names shared by L3, L4, and downstream pipeline layers."""

    # Canonical L3 producer names.
    PERSON_EN = "PERSON_EN"
    LOCATION = "LOCATION"
    ADDRESS = "ADDRESS"
    AGE = "AGE"
    AGE_GROUP = "AGE_GROUP"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    KR_RRN = "KR_RRN"
    PHONE_NUMBER = "PHONE_NUMBER"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    KR_PASSPORT = "KR_PASSPORT"
    KR_FRN = "KR_FRN"
    KR_DRIVER_LICENSE = "KR_DRIVER_LICENSE"
    KR_BRN = "KR_BRN"

    PERSON_KO = "PERSON_KO"
    LOCATION_INFORMAL = "LOCATION_INFORMAL"
    CUSTOMS_CLEARANCE_ID = "CUSTOMS_CLEARANCE_ID"
    ORDER_ID = "ORDER_ID"
    TRACKING_NUMBER = "TRACKING_NUMBER"
    CUSTOMER_ID = "CUSTOMER_ID"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    ADDRESS_ROAD = "ADDRESS_ROAD"
    ADDRESS_LOT = "ADDRESS_LOT"
    ADDRESS_DETAIL = "ADDRESS_DETAIL"
    SENSITIVE_HEALTH = "SENSITIVE_HEALTH"
    SENSITIVE_SEX_LIFE = "SENSITIVE_SEX_LIFE"
    PRODUCT_ITEM = "PRODUCT_ITEM"
    PURCHASE_PATTERN = "PURCHASE_PATTERN"


class DetectionTier(StrEnum):
    """Evidence strength for one detection instance."""

    DETERMINISTIC = "deterministic"
    RULE_ANCHORED = "rule_anchored"
    MODEL = "model"
    CANDIDATE = "candidate"


class UserContext(BaseModel):
    """Authenticated user information produced by L1."""

    user_id: str
    department: str
    role: str
    allowed_models: list[str] = Field(default_factory=lambda: ["gpt-5", "gpt-4o-mini"])
    restore_level: str = "default"


class TextSegment(BaseModel):
    """One text-bearing request segment produced by L2."""

    segment_id: str
    path: str
    role: str | None = "user"
    text: str


class ParsedRequest(BaseModel):
    """Vendor-neutral request representation."""

    vendor: str = "openai"
    model: str
    segments: list[TextSegment]
    original_body: dict[str, Any]


class DetectedPII(BaseModel):
    """Canonical nine-field L3/L4 detection contract.

    ``start_idx`` and ``end_idx`` are zero-based, half-open offsets into the
    shared ``ProxyContext.raw_prompt``.

    ``confidence`` is required but may explicitly be ``None``.

    ``tier`` is required and must explicitly identify one evidence tier.

    Transitional defaults for ``segment_id``, ``source``, and ``normalized``
    are preserved until the legacy mock / multi-segment boundary is migrated
    without inventing PD-010 coordinate semantics.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    # Canonical nine-field order.
    segment_id: str = "seg-1"
    start_idx: int = Field(ge=0)
    end_idx: int = Field(gt=0)
    entity_type: EntityType | str
    confidence: float | None = Field(..., ge=0.0, le=1.0)
    source: str = Field(
        default="unknown",
        description="탐지 출처 (예: L3_Regex, L4_BERT)",
    )
    tier: DetectionTier
    original_value: str = Field(min_length=1)
    normalized: str = ""

    @property
    def layer(self) -> str:
        """Backward-compatible read-only alias for old L5 callers."""
        return self.source

    @model_validator(mode="after")
    def validate_span(self) -> "DetectedPII":
        if self.end_idx <= self.start_idx:
            raise ValueError("invalid detected entity span")
        return self


class EntityPolicy(BaseModel):
    """L5가 탐지 항목 하나에 대해 정한 처리 방식. 원문 값은 담지 않는다.

    ``action``은 요청 단위 ``policy_action``과 같은 어휘(TOKENIZE/GENERALIZE/ALLOW)를
    쓰고, L6는 항목별 action이 있으면 그것을, 없으면 요청 단위 값을 따른다.
    """

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    start_idx: int = Field(ge=0)
    end_idx: int = Field(gt=0)
    entity_type: str
    privacy_class: str
    action: Literal["TOKENIZE", "GENERALIZE", "ALLOW"]
    reason: str


class ProxyContext(BaseModel):
    """Shared mutable context passed through the L1-L9 pipeline."""

    model_config = ConfigDict(validate_assignment=True, hide_input_in_errors=True)

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        frozen=True,
    )

    user: UserContext | None = None
    user_role: str = "intern"
    parsed_request: ParsedRequest | None = None
    raw_prompt: str = Field(default="", exclude=True)
    status: str = "success"
    error: str | None = None

    detected_entities: list[DetectedPII] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_level: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    policy_action: str | None = None
    entity_policies: list[EntityPolicy] = Field(default_factory=list)

    anonymized_prompt: str | None = None
    vault_mapping: dict[str, str] = Field(default_factory=dict)
    token_types: dict[str, str] = Field(default_factory=dict)

    reconstructed_body: dict[str, Any] = Field(default_factory=dict)
    upstream_request_body: dict[str, Any] = Field(
        default_factory=dict,
        exclude=True,
        repr=False,
    )
    llm_raw_response: Any = Field(default=None, exclude=True)
    final_response: Any = Field(default=None, exclude=True)
    final_response_log: str | None = Field(default=None, exclude=True)
    latency_ms: dict[str, float] = Field(default_factory=dict)

    def validate_detected_spans(self) -> None:
        """Validate every detection against the canonical raw-prompt offsets."""
        for entity in self.detected_entities:
            actual = self.raw_prompt[entity.start_idx : entity.end_idx]
            if actual != entity.original_value:
                raise ValueError("detected entity span mismatch")
