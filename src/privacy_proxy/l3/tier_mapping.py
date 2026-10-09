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
) -> DetectionTier:
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
    if entity == "AGE":
        # Exact producer identity is verified above. Its analyze method emits
        # only after numeric, clause, anchor, semantic and lexical checks.
        # Context cannot be reconstructed from the surface alone; no score
        # inference or shared last-request evidence is used here.
        return DetectionTier.RULE_ANCHORED
    if entity == "AGE_GROUP":
        # Exact producer type is verified above. Emission requires the H1-R1
        # anchor, gap, clause and semantic checks, never a numeric score.
        return DetectionTier.RULE_ANCHORED
    if entity == "DATE_OF_BIRTH":
        # Exact producer identity is verified above. DOB emission requires
        # approved birth-context evidence plus Gregorian/date-bound checks.
        # That context is not reconstructible from the emitted raw slice alone.
        return DetectionTier.RULE_ANCHORED
    if entity == "KR_PASSPORT":
        return DetectionTier.RULE_ANCHORED
    if entity in ("KR_RRN", "KR_FRN"):
        # Re-run the actual producer validator on the emitted raw slice. A score
        # or entity label alone is not checksum evidence.
        try:
            validation_result = producer.validate_result(original_value)
        except Exception:
            raise ProvenanceError("EMITTED_VALIDATION_FAILED") from None
        if validation_result is True:
            return DetectionTier.DETERMINISTIC
        if validation_result is None:
            return DetectionTier.RULE_ANCHORED
        raise ProvenanceError("EMITTED_VALIDATION_NOT_RETAINED")
    raise ProvenanceError("UNMAPPED_TIER_PRODUCER")
