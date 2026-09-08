"""Shared data contracts passed through the L1-L9 pipeline."""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetectedPII(BaseModel):
    """PII detected by L3/L4, using Python's half-open slice indexes."""

    entity_type: str
    original_value: str
    start_idx: int
    end_idx: int
    layer: str
    confidence: float = 1.0

    @model_validator(mode="after")
    def validate_span(self) -> "DetectedPII":
        if self.start_idx < 0:
            raise ValueError("start_idx must be non-negative")
        if self.end_idx <= self.start_idx:
            raise ValueError("end_idx must be greater than start_idx")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return self


class ProxyContext(BaseModel):
    """Single shared context object for the L1-L9 pipeline."""

    model_config = ConfigDict(validate_assignment=True)

    # L1 / L2 immutable fields
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_prompt: str = Field(..., frozen=True, exclude=True)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        frozen=True,
    )

    # L1 / L2 mutable fields
    user_role: str = "intern"
    status: str = "success"
    error: str | None = None

    # L3-L5
    detected_entities: list[DetectedPII] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_level: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    policy_action: str | None = None

    # L6
    anonymized_prompt: str | None = None
    vault_mapping: dict[str, str] = Field(default_factory=dict)
    token_types: dict[str, str] = Field(default_factory=dict)

    # L7
    llm_raw_response: str | None = None

    # L8
    final_response: str | None = None

    # L9
    latency_ms: dict[str, float] = Field(default_factory=dict)

    def validate_detected_spans(self) -> None:
        """Check the L3/L4 offset contract against the immutable raw prompt."""
        for entity in self.detected_entities:
            actual = self.raw_prompt[entity.start_idx : entity.end_idx]
            if actual != entity.original_value:
                raise ValueError(
                    "detected entity span mismatch: "
                    f"expected {entity.original_value!r}, got {actual!r}"
                )
