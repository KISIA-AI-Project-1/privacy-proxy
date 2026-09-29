"""Trusted producer-side output only. Does not call or define an L5 consumer."""

from dataclasses import dataclass

from privacy_proxy.contracts.detection import Detection


@dataclass(frozen=True, repr=False)
class L3Output:
    raw_prompt: str
    detections: tuple[Detection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.raw_prompt, str):
            raise ValueError("RAW_PROMPT_TYPE")
        if not isinstance(self.detections, tuple):
            raise ValueError("DETECTIONS_TUPLE_REQUIRED")
        for detection in self.detections:
            if not isinstance(detection, Detection):
                raise ValueError("DETECTION_TYPE")
            Detection(
                segment_id=detection.segment_id,
                start_idx=detection.start_idx,
                end_idx=detection.end_idx,
                entity_type=detection.entity_type,
                confidence=detection.confidence,
                source=detection.source,
                tier=detection.tier,
                original_value=detection.original_value,
                normalized=detection.normalized,
                raw_prompt=self.raw_prompt,
            )
            if detection.confidence is not None:
                raise ValueError("L3_CONFIDENCE_MUST_BE_NULL")
        if len({item.segment_id for item in self.detections}) > 1:
            raise ValueError("MULTI_SEGMENT_NOT_IMPLEMENTED")
