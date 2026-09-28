import logging
import unittest

from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3.service import L3AnalyzerService
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
            self.assertEqual(set(detection.to_dict()), KEYS)
            self.assertIsNone(detection.confidence)
            self.assertTrue(detection.source)
            self.assertEqual(detection.segment_id, "seg-3")
            self.assertEqual(raw[detection.start_idx : detection.end_idx], detection.original_value)
            self.assertEqual(detection.normalized, detection.original_value)
        return detections

    def test_brn_valid_hyphenated(self):
        detected = self.detect("KR_BRN", BRN_VALID)
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].tier, "DETERMINISTIC")

    def test_brn_invalid_rejected(self):
        self.assertEqual(self.detect("KR_BRN", BRN_INVALID), [])

    def test_brn_compact_current_behavior_preserved(self):
        self.assertEqual(len(self.detect("KR_BRN", BRN_COMPACT)), 1)

    def test_passport_formats(self):
        for value in [PASSPORT, PASSPORT_OLD]:
            detected = self.detect("KR_PASSPORT", value)
            self.assertEqual(len(detected), 1)
            self.assertEqual(detected[0].tier, "RULE_ANCHORED")

    def test_license_structural_validation(self):
        detected = self.detect("KR_DRIVER_LICENSE", LICENSE_VALID)
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].tier, "DETERMINISTIC")
        self.assertEqual(self.detect("KR_DRIVER_LICENSE", LICENSE_INVALID), [])

    def test_rrn_soft_retention(self):
        for value in [RRN_VALID, RRN_SOFT]:
            detected = self.detect("KR_RRN", value)
            self.assertEqual(len(detected), 1)
            self.assertIsNone(detected[0].tier)

    def test_frn_soft_retention(self):
        for value in [FRN_VALID, FRN_SOFT]:
            detected = self.detect("KR_FRN", value)
            self.assertEqual(len(detected), 1)
            self.assertIsNone(detected[0].tier)

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
