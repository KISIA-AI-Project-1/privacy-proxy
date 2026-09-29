"""PD-004 mapping for verified producers; numeric scores are never evidence."""

from typing import Any

import phonenumbers

from privacy_proxy.schemas import DetectionTier

from .provenance import ProvenanceError
from .registry import PRODUCER_TYPES


def tier_for(
    producer: Any,
    entity: str,
    original_value: str,
) -> DetectionTier | None:
    if entity not in PRODUCER_TYPES or type(producer) is not PRODUCER_TYPES[entity]:
        raise ProvenanceError("UNVERIFIED_TIER_PRODUCER")
    if entity in ("KR_BRN", "KR_DRIVER_LICENSE"):
        # Recheck the exact emitted raw slice with the same installed validator.
        # This confirms per-instance validity, not an entity-wide assumption.
        if producer.validate_result(original_value) is not True:
            raise ProvenanceError("EMITTED_VALIDATION_NOT_PASS")
        return DetectionTier.DETERMINISTIC
    if entity == "PHONE_NUMBER":
        # Exact producer identity is checked above and by provenance resolution.
        # Reverify this raw slice through the same parser/leniency path; neither
        # a score nor the entity label proves parser-supported emission.
        matches = phonenumbers.PhoneNumberMatcher(
            original_value,
            producer.supported_regions[0],
            leniency=producer.leniency,
        )
        if not any(m.start == 0 and m.end == len(original_value) for m in matches):
            raise ProvenanceError("EMITTED_PHONE_PARSER_NOT_PASS")
        return DetectionTier.RULE_ANCHORED
    if entity == "EMAIL_ADDRESS":
        # Re-run the verified pattern and protected validator on the raw slice.
        # Score alone is not evidence; a substring match is insufficient.
        matches = producer.analyze(original_value, ["EMAIL_ADDRESS"])
        if not any(r.start == 0 and r.end == len(original_value) for r in matches):
            raise ProvenanceError("EMITTED_EMAIL_PATTERN_NOT_PASS")
        return DetectionTier.RULE_ANCHORED
    if entity == "KR_PASSPORT":
        return DetectionTier.RULE_ANCHORED
    # The service does not retain analysis explanations. Do not infer RRN/FRN
    # checksum outcome from 1.0/0.5 scores or their entity names.
    return None
