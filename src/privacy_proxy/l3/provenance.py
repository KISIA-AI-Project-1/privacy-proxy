"""Preserve actual producer names without defining canonical source names."""

from typing import Any

from presidio_analyzer import RecognizerResult

from .registry import validate_registry


class ProvenanceError(ValueError):
    """Unknown or contradictory producer evidence."""


def resolve_producer(
    result: RecognizerResult,
    registry: Any,
) -> Any:
    producers = validate_registry(registry)
    producer = producers.get(result.entity_type)
    if producer is None:
        raise ProvenanceError("UNKNOWN_PRODUCER_ENTITY")
    metadata = result.recognition_metadata
    if metadata is not None and not isinstance(metadata, dict):
        raise ProvenanceError("PRODUCER_METADATA_TYPE")
    metadata = metadata or {}
    for key, expected in (
        (RecognizerResult.RECOGNIZER_NAME_KEY, producer.name),
        (RecognizerResult.RECOGNIZER_IDENTIFIER_KEY, producer.id),
    ):
        if key in metadata and metadata[key] != expected:
            raise ProvenanceError("PRODUCER_METADATA_CONFLICT")
    # Missing metadata is supported only because validate_registry proves a
    # single actual producer for this entity. Explicit empty/conflicting values fail.
    return producer
