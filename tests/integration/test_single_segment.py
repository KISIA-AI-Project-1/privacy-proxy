import logging
import unittest

from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectedPII, DetectionTier
from tests.fixtures import (
    BRN_COMPACT,
    BRN_INVALID,
    BRN_VALID,
    FRN_SOFT,
    FRN_VALID,
    KEYS,
    LICENSE_INVALID,
    LICENSE_VALID,
    PASSPORT,
    PASSPORT_OLD,
    RRN_SOFT,
    RRN_VALID,
)


class SingleSegmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = L3AnalyzerService()

    def detect(self, entity, value):
        # Leading Korean codepoints exercise Python raw offsets, not byte offsets.
        raw = "\uac80\uc0ac: " + value + " !"
        detections = self.service.analyze(raw, "seg-3", entities=[entity])
        for detection in detections:
            self.assertIsInstance(detection, DetectedPII)
            self.assertEqual(set(detection.model_dump()), KEYS)
            self.assertIsNone(detection.confidence)
            self.assertTrue(detection.source)
            self.assertEqual(detection.segment_id, "seg-3")
            self.assertEqual(raw[detection.start_idx : detection.end_idx], detection.original_value)
            self.assertEqual(detection.normalized, detection.original_value)
            if detection.tier is not None:
                self.assertIsInstance(detection.tier, DetectionTier)
        return detections

    def test_resolved_producers_conform_to_canonical_schema(self):
        cases = (
            ("KR_PASSPORT", PASSPORT, "KrPassportRecognizer"),
            ("KR_DRIVER_LICENSE", LICENSE_VALID, "KrDriverLicenseRecognizer"),
            ("KR_BRN", BRN_VALID, "KrBrnRecognizer"),
            ("PHONE_NUMBER", "010-2000-0000", "PhoneRecognizer"),
            ("EMAIL_ADDRESS", "audit@example.com", "EmailRecognizer"),
        )

        for entity, value, expected_source in cases:
            with self.subTest(entity=entity):
                raw = "검사: " + value + " !"
                detections = self.service.analyze(raw, "canonical-segment", entities=[entity])
                self.assertEqual(len(detections), 1)

                payload = detections[0].model_dump()
                self.assertEqual(tuple(payload), tuple(DetectedPII.model_fields))
                self.assertEqual(set(payload), KEYS)

                canonical = DetectedPII.model_validate(payload)
                self.assertIsInstance(canonical.tier, DetectionTier)
                self.assertIsNotNone(canonical.tier)
                self.assertIsNone(canonical.confidence)
                self.assertEqual(canonical.source, expected_source)
                self.assertTrue(0 <= canonical.start_idx < canonical.end_idx <= len(raw))
                self.assertEqual(
                    raw[canonical.start_idx : canonical.end_idx],
                    canonical.original_value,
                )
                self.assertEqual(canonical.normalized, canonical.original_value)

                json_payload = canonical.model_dump(mode="json")
                self.assertEqual(tuple(json_payload), tuple(DetectedPII.model_fields))
                self.assertEqual(json_payload["tier"], canonical.tier.value)
                self.assertEqual(json_payload["tier"], json_payload["tier"].lower())

    def test_brn_valid_hyphenated(self):
        detected = self.detect("KR_BRN", BRN_VALID)
        self.assertEqual(len(detected), 1)
        self.assertIs(detected[0].tier, DetectionTier.DETERMINISTIC)

    def test_brn_invalid_rejected(self):
        self.assertEqual(self.detect("KR_BRN", BRN_INVALID), [])

    def test_brn_compact_current_behavior_preserved(self):
        self.assertEqual(len(self.detect("KR_BRN", BRN_COMPACT)), 1)

    def test_passport_formats(self):
        for value in [PASSPORT, PASSPORT_OLD]:
            detected = self.detect("KR_PASSPORT", value)
            self.assertEqual(len(detected), 1)
            self.assertIs(detected[0].tier, DetectionTier.RULE_ANCHORED)

    def test_license_structural_validation(self):
        detected = self.detect("KR_DRIVER_LICENSE", LICENSE_VALID)
        self.assertEqual(len(detected), 1)
        self.assertIs(detected[0].tier, DetectionTier.DETERMINISTIC)
        self.assertEqual(self.detect("KR_DRIVER_LICENSE", LICENSE_INVALID), [])

    def test_rrn_validation_tiers_conform_to_canonical_schema(self):
        for value, expected_tier in (
            (RRN_VALID, DetectionTier.DETERMINISTIC),
            (RRN_SOFT, DetectionTier.RULE_ANCHORED),
        ):
            detected = self.detect("KR_RRN", value)
            self.assertEqual(len(detected), 1)
            canonical = DetectedPII.model_validate(detected[0].model_dump())
            self.assertIs(canonical.tier, expected_tier)
            self.assertEqual(canonical.source, "KrRrnRecognizer")

    def test_frn_validation_tiers_conform_to_canonical_schema(self):
        for value, expected_tier in (
            (FRN_VALID, DetectionTier.DETERMINISTIC),
            (FRN_SOFT, DetectionTier.RULE_ANCHORED),
        ):
            detected = self.detect("KR_FRN", value)
            self.assertEqual(len(detected), 1)
            canonical = DetectedPII.model_validate(detected[0].model_dump())
            self.assertIs(canonical.tier, expected_tier)
            self.assertEqual(canonical.source, "KrFrnRecognizer")

    def test_default_subset_and_producer_boundary(self):
        raw = " | ".join([RRN_VALID, FRN_VALID, PASSPORT, LICENSE_VALID, BRN_VALID])
        detections = self.service.analyze(raw, "s")
        self.assertEqual(
            {d.entity_type for d in detections},
            {"KR_RRN", "KR_FRN", "KR_PASSPORT", "KR_DRIVER_LICENSE", "KR_BRN"},
        )
        self.assertEqual(len(detections), 5)
        output = L3Output(raw, tuple(detections))
        self.assertEqual(len(output.detections), 5)

    def test_no_raw_value_in_dependency_or_application_logs(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("presidio-analyzer")
        old_level = logger.level
        handler = Capture()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            self.detect("KR_BRN", BRN_VALID)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        self.assertFalse(any(BRN_VALID in message for message in records))

    def test_empty_prompt_is_successful_no_detection(self):
        self.assertEqual(self.service.analyze("", "s"), [])


# Future test boundary (not current expected behavior):
# BLOCKED_BY_MENTOR: individual/corporate and hyphen-only KR_BRN scope.
# BLOCKED_BY_PD010: multi-segment coordinates. No L5 consumer exists here.
