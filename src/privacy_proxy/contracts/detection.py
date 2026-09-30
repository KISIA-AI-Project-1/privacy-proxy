"""Privacy-safe raw-coordinate validation helpers for detection boundaries."""


class DetectionValidationError(ValueError):
    """Reason codes only: never interpolate sensitive input."""


def validate_span(raw_prompt: str, start: int, end: int) -> None:
    if not isinstance(raw_prompt, str):
        raise DetectionValidationError("RAW_PROMPT_TYPE")
    if type(start) is not int or type(end) is not int:
        raise DetectionValidationError("SPAN_TYPE")
    if not 0 <= start < end <= len(raw_prompt):
        raise DetectionValidationError("SPAN_BOUNDS")
