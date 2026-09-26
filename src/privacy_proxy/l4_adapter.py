"""Adapters from L4-local detections to the canonical pipeline contract."""

from privacy_proxy.schemas import DetectedPII, DetectionTier

KLUE_TO_CANONICAL_ENTITY = {
    "PS": "PERSON_KO",
    "LC": "LOCATION_INFORMAL",
}


def adapt_klue_span(
    *,
    label: str,
    segment_text: str,
    start_idx: int,
    end_idx: int,
    confidence: float,
    segment_id: str,
    offset_base: int,
    source: str = "L4_KLUE_NER",
) -> DetectedPII:
    """Map a KLUE label and translate its segment-local span to raw_prompt."""
    if label not in KLUE_TO_CANONICAL_ENTITY:
        raise ValueError(f"unsupported KLUE entity label: {label}")
    if offset_base < 0:
        raise ValueError("offset_base must be non-negative")
    if start_idx < 0 or end_idx <= start_idx or end_idx > len(segment_text):
        raise ValueError("invalid segment-local span")

    original_value = segment_text[start_idx:end_idx]
    return DetectedPII(
        entity_type=KLUE_TO_CANONICAL_ENTITY[label],
        original_value=original_value,
        start_idx=offset_base + start_idx,
        end_idx=offset_base + end_idx,
        confidence=confidence,
        segment_id=segment_id,
        normalized=original_value,
        tier=DetectionTier.MODEL,
        source=source,
    )


def translate_segment_detection(
    detection: DetectedPII,
    *,
    offset_base: int,
) -> DetectedPII:
    """Translate an L4 recognizer detection from segment-local to global offsets."""
    if offset_base < 0:
        raise ValueError("offset_base must be non-negative")
    payload = detection.model_dump(mode="python")
    payload["start_idx"] = detection.start_idx + offset_base
    payload["end_idx"] = detection.end_idx + offset_base
    return DetectedPII.model_validate(payload)
