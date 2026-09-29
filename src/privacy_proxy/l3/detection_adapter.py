"""Raw-coordinate preserving adapter; no overlap, risk, or scope policy."""

from typing import Any

from presidio_analyzer import RecognizerResult

from privacy_proxy.contracts.detection import Detection, validate_span

from .provenance import resolve_producer
from .tier_mapping import tier_for


def adapt_result(
    result: RecognizerResult,
    raw_prompt: str,
    segment_id: str,
    registry: Any,
) -> Detection:
    validate_span(raw_prompt, result.start, result.end)
    producer = resolve_producer(result, registry)
    original = raw_prompt[result.start : result.end]
    return Detection(
        segment_id=segment_id,
        start_idx=result.start,
        end_idx=result.end,
        entity_type=result.entity_type,
        confidence=None,
        source=producer.name,
        tier=tier_for(producer, result.entity_type, original),
        original_value=original,
        normalized=original,
        raw_prompt=raw_prompt,
    )
