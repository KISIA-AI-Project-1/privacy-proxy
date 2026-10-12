"""Trusted producer-side output only. Does not call or define an L5 consumer."""

from dataclasses import dataclass

from pydantic import ValidationError

from privacy_proxy.contracts.detection import DetectionValidationError, validate_span
from privacy_proxy.schemas import DetectedPII


@dataclass(frozen=True, repr=False)
class L3Output:
    raw_prompt: str
    detections: tuple[DetectedPII, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.raw_prompt, str):
            raise ValueError("RAW_PROMPT_TYPE")
        if not isinstance(self.detections, tuple):
            raise ValueError("DETECTIONS_TUPLE_REQUIRED")
        segment_ids: set[str] = set()
        for detection in self.detections:
            if not isinstance(detection, DetectedPII):
                raise ValueError("DETECTION_TYPE")
            try:
                canonical = DetectedPII.model_validate(detection.model_dump())
            except ValidationError:
                raise ValueError("DETECTION_SCHEMA") from None
            validate_span(self.raw_prompt, canonical.start_idx, canonical.end_idx)
            if self.raw_prompt[canonical.start_idx : canonical.end_idx] != canonical.original_value:
                raise DetectionValidationError("ORIGINAL_VALUE_MISMATCH")
            if canonical.confidence is not None:
                raise ValueError("L3_CONFIDENCE_MUST_BE_NULL")
            segment_ids.add(canonical.segment_id)
        if len(segment_ids) > 1:
            raise ValueError("MULTI_SEGMENT_NOT_IMPLEMENTED")
