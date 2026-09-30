"""PD-005 nine-key model. raw_prompt is validation input, never a field."""

from dataclasses import InitVar, asdict, dataclass

from privacy_proxy.schemas import DetectionTier


class DetectionValidationError(ValueError):
    """Reason codes only: never interpolate sensitive input."""


def validate_span(raw_prompt: str, start: int, end: int) -> None:
    if not isinstance(raw_prompt, str):
        raise DetectionValidationError("RAW_PROMPT_TYPE")
    if type(start) is not int or type(end) is not int:
        raise DetectionValidationError("SPAN_TYPE")
    if not 0 <= start < end <= len(raw_prompt):
        raise DetectionValidationError("SPAN_BOUNDS")


@dataclass(frozen=True, repr=False)
class Detection:
    segment_id: str
    start_idx: int
    end_idx: int
    entity_type: str
    confidence: float | None
    source: str
    tier: DetectionTier | None
    original_value: str
    normalized: str
    raw_prompt: InitVar[str]

    def __post_init__(self, raw_prompt: str) -> None:
        for name in ("segment_id", "entity_type", "source"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DetectionValidationError(name.upper() + "_REQUIRED")
        if self.source.strip() in ("L3", "L4"):
            raise DetectionValidationError("SOURCE_LAYER_ONLY")
        if self.confidence is not None:
            try:
                confidence = float(self.confidence)
            except (TypeError, ValueError, OverflowError):
                raise DetectionValidationError("CONFIDENCE_TYPE") from None
            if not 0.0 <= confidence <= 1.0:
                raise DetectionValidationError("CONFIDENCE_RANGE")
            object.__setattr__(self, "confidence", confidence)
        if self.tier is not None and not isinstance(self.tier, DetectionTier):
            raise DetectionValidationError("TIER_VALUE")
        if not isinstance(self.normalized, str):
            raise DetectionValidationError("NORMALIZED_TYPE")
        validate_span(raw_prompt, self.start_idx, self.end_idx)
        if not isinstance(self.original_value, str) or (
            raw_prompt[self.start_idx : self.end_idx] != self.original_value
        ):
            raise DetectionValidationError("ORIGINAL_VALUE_MISMATCH")

    def to_dict(self) -> dict[str, object]:
        """Always serialize all nine keys, including both nullable fields."""
        return asdict(self)
