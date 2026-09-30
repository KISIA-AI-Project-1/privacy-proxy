import unittest
from dataclasses import FrozenInstanceError

from privacy_proxy.contracts.detection import Detection, DetectionValidationError
from privacy_proxy.schemas import DetectionTier
from tests.fixtures import KEYS


class DetectionTests(unittest.TestCase):
    def values(self):
        return {
            "segment_id": "seg-1",
            "start_idx": 1,
            "end_idx": 4,
            "entity_type": "KR_PASSPORT",
            "confidence": None,
            "source": "ActualProducer",
            "tier": None,
            "original_value": "abc",
            "normalized": "abc",
            "raw_prompt": "!abc!",
        }

    def test_exact_serialization_and_null_keys(self):
        result = Detection(**self.values()).to_dict()
        self.assertEqual(set(result), KEYS)
        self.assertIsNone(result["confidence"])
        self.assertIsNone(result["tier"])

    def test_all_fields_required(self):
        for field in KEYS:
            values = self.values()
            del values[field]
            with self.subTest(field=field), self.assertRaises(TypeError):
                Detection(**values)

    def test_invalid_spans(self):
        for start, end in [(-1, 3), (3, 3), (4, 2), (1, 99), (True, 4), (1.0, 4)]:
            values = self.values()
            values.update(start_idx=start, end_idx=end)
            with self.subTest(start=start, end=end), self.assertRaises(DetectionValidationError):
                Detection(**values)

    def test_mismatch_rejected(self):
        values = self.values()
        values["original_value"] = "mismatch"
        with self.assertRaisesRegex(DetectionValidationError, "ORIGINAL_VALUE_MISMATCH"):
            Detection(**values)

    def test_non_null_and_nonempty_policies(self):
        for key, value in [
            ("normalized", None),
            ("original_value", None),
            ("source", ""),
            ("source", None),
            ("source", "L3"),
            ("segment_id", None),
            ("segment_id", " "),
            ("entity_type", ""),
            ("confidence", "high"),
        ]:
            values = self.values()
            values[key] = value
            with self.subTest(key=key), self.assertRaises(DetectionValidationError):
                Detection(**values)

    def test_confidence_uses_canonical_coercion_and_range(self):
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
            values = self.values()
            values["confidence"] = confidence
            actual = Detection(**values).confidence
            self.assertEqual(actual, expected)
            if actual is not None:
                self.assertIs(type(actual), float)

        for confidence in (-0.1, 1.1, float("nan"), float("inf")):
            values = self.values()
            values["confidence"] = confidence
            with self.subTest(confidence=confidence), self.assertRaises(DetectionValidationError):
                Detection(**values)

    def test_tier_vocabulary(self):
        for tier in [None, *DetectionTier]:
            values = self.values()
            values["tier"] = tier
            self.assertIs(Detection(**values).tier, tier)
        for tier in [
            "DETERMINISTIC",
            "RULE_ANCHORED",
            "MODEL",
            "CANDIDATE",
            "deterministic",
            [],
        ]:
            values = self.values()
            values["tier"] = tier
            with self.assertRaises(DetectionValidationError):
                Detection(**values)

    def test_normalized_does_not_require_raw_equality(self):
        values = self.values()
        values["normalized"] = "ABC"
        self.assertEqual(Detection(**values).normalized, "ABC")

    def test_immutable_and_repr_private(self):
        detection = Detection(**self.values())
        self.assertNotIn("abc", repr(detection))
        with self.assertRaises(FrozenInstanceError):
            detection.original_value = "changed"
