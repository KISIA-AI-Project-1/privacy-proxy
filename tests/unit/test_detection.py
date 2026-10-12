import unittest

from pydantic import ValidationError

from privacy_proxy.contracts.detection import DetectionValidationError, validate_span
from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.schemas import DetectedPII, DetectionTier
from tests.fixtures import KEYS


class DetectionBoundaryTests(unittest.TestCase):
    def detection(self, **overrides):
        values = {
            "segment_id": "seg-1",
            "start_idx": 1,
            "end_idx": 4,
            "entity_type": "KR_PASSPORT",
            "confidence": None,
            "source": "ActualProducer",
            "tier": DetectionTier.RULE_ANCHORED,
            "original_value": "abc",
            "normalized": "abc",
        }
        values.update(overrides)
        return DetectedPII(**values)

    def test_canonical_serialization_has_exact_nine_fields(self):
        detection = self.detection()
        payload = detection.model_dump()
        self.assertEqual(tuple(payload), tuple(DetectedPII.model_fields))
        self.assertEqual(set(payload), KEYS)
        self.assertIsNone(payload["confidence"])
        self.assertIs(payload["tier"], DetectionTier.RULE_ANCHORED)

    def test_validate_span_accepts_valid_raw_coordinates(self):
        validate_span("!abc!", 1, 4)

    def test_validate_span_rejects_invalid_coordinates(self):
        for start, end in ((-1, 3), (3, 3), (4, 2), (1, 99), (True, 4), (1.0, 4)):
            with self.subTest(start=start, end=end), self.assertRaises(DetectionValidationError):
                validate_span("!abc!", start, end)

    def test_canonical_confidence_coercion_and_range(self):
        for confidence, expected in (
            (None, None),
            (0.0, 0.0),
            (0.5, 0.5),
            (1.0, 1.0),
            (0, 0.0),
            (1, 1.0),
            (True, 1.0),
            (False, 0.0),
            ("0.5", 0.5),
        ):
            with self.subTest(confidence=confidence):
                self.assertEqual(self.detection(confidence=confidence).confidence, expected)
        for confidence in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(confidence=confidence), self.assertRaises(ValidationError):
                self.detection(confidence=confidence)

    def test_l3_output_accepts_canonical_tuple(self):
        detection = self.detection()
        output = L3Output("!abc!", (detection,))
        self.assertEqual(output.detections, (detection,))
        self.assertNotIn("abc", repr(output))

    def test_l3_output_requires_tuple_and_canonical_items(self):
        detection = self.detection()
        with self.assertRaisesRegex(ValueError, "TUPLE"):
            L3Output("!abc!", [detection])
        with self.assertRaisesRegex(ValueError, "DETECTION_TYPE"):
            L3Output("!abc!", (object(),))

    def test_l3_output_rejects_non_null_confidence(self):
        with self.assertRaisesRegex(ValueError, "CONFIDENCE"):
            L3Output("!abc!", (self.detection(confidence=0.5),))

    def test_l3_output_rejects_end_beyond_raw_prompt(self):
        with self.assertRaisesRegex(DetectionValidationError, "SPAN_BOUNDS"):
            L3Output("!abc!", (self.detection(end_idx=99),))

    def test_l3_output_rejects_invalid_ordering(self):
        invalid = DetectedPII.model_construct(
            segment_id="seg-1",
            start_idx=4,
            end_idx=2,
            entity_type="KR_PASSPORT",
            confidence=None,
            source="ActualProducer",
            tier=DetectionTier.RULE_ANCHORED,
            original_value="abc",
            normalized="abc",
        )
        with self.assertRaisesRegex(ValueError, "DETECTION_SCHEMA"):
            L3Output("!abc!", (invalid,))

    def test_l3_output_rejects_raw_binding_mismatch_without_pii(self):
        private_value = "private-value"
        detection = self.detection(original_value=private_value)
        with self.assertRaisesRegex(DetectionValidationError, "ORIGINAL_VALUE_MISMATCH") as caught:
            L3Output("!abc!", (detection,))
        self.assertNotIn(private_value, str(caught.exception))

    def test_l3_output_rejects_multiple_segments(self):
        with self.assertRaisesRegex(ValueError, "MULTI_SEGMENT"):
            L3Output(
                "!abc!",
                (
                    self.detection(segment_id="seg-1"),
                    self.detection(segment_id="seg-2"),
                ),
            )
