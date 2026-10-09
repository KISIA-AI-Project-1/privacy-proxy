"""PHONE vNext capability/provenance tests; no new policy vocabulary."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from presidio_analyzer import PatternRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import PhoneRecognizer

from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.provenance import ProvenanceError
from privacy_proxy.l3.registry import RegistryConfigurationError, build_registry, validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, UnsupportedCapabilityError
from privacy_proxy.l3.timeout_guard import _TimeoutMatcher, protect_patterns
from privacy_proxy.schemas import DetectionTier

# phonenumbers example metadata fixture, frozen STEP7A PHONE case P03.
PHONE = "010-2000-0000"


class PhoneUnitTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.phone = validate_registry(self.registry)["PHONE_NUMBER"]

    def result(self, value=PHONE, score=0.4):
        return RecognizerResult(
            "PHONE_NUMBER",
            0,
            len(value),
            score,
            recognition_metadata={
                "recognizer_name": self.phone.name,
                "recognizer_identifier": self.phone.id,
            },
        )

    def test_exact_eleven_and_phone_configuration(self):
        self.assertEqual(
            set(validate_registry(self.registry)),
            {
                "KR_RRN",
                "KR_FRN",
                "KR_PASSPORT",
                "KR_DRIVER_LICENSE",
                "KR_BRN",
                "PHONE_NUMBER",
                "EMAIL_ADDRESS",
                "AGE",
                "AGE_GROUP",
                "DATE_OF_BIRTH",
                "LOCATION",
            },
        )
        self.assertIs(type(self.phone), PhoneRecognizer)
        self.assertEqual(self.phone.supported_language, "ko")
        self.assertEqual(self.phone.supported_regions, ("KR",))
        self.assertEqual(self.phone.leniency, 1)
        self.assertEqual(
            sum("PHONE_NUMBER" in r.supported_entities for r in self.registry.recognizers), 1
        )

    def test_duplicate_phone_rejected(self):
        self.registry.recognizers.append(
            PhoneRecognizer(supported_language="ko", supported_regions=("KR",))
        )
        with self.assertRaisesRegex(RegistryConfigurationError, "DUPLICATE"):
            validate_registry(self.registry)

    def test_changed_parser_configuration_fails(self):
        for key, value in [("supported_regions", ("US",)), ("leniency", 0)]:
            with (
                self.subTest(key=key),
                patch.object(self.phone, key, value),
                self.assertRaisesRegex(RegistryConfigurationError, "PHONE_PARSER"),
            ):
                validate_registry(self.registry)

    def test_parser_evidence_not_score(self):
        for score in (0.0, 0.4, 1.0):
            detection = adapt_result(self.result(score=score), PHONE, "s", self.registry)
            self.assertIs(detection.tier, DetectionTier.RULE_ANCHORED)
            self.assertIsNone(detection.confidence)
        with self.assertRaisesRegex(ProvenanceError, "PHONE_PARSER"):
            adapt_result(self.result("123", 1.0), "123", "s", self.registry)

    def test_parser_recheck_must_cover_exact_span(self):
        with (
            patch(
                "privacy_proxy.l3.tier_mapping.phonenumbers.PhoneNumberMatcher",
                return_value=iter([SimpleNamespace(start=1, end=len(PHONE))]),
            ),
            self.assertRaisesRegex(ProvenanceError, "PHONE_PARSER"),
        ):
            adapt_result(self.result(), PHONE, "s", self.registry)

    def test_metadata_conflict_fails(self):
        for metadata in ({"recognizer_name": "L3"}, {"recognizer_identifier": "wrong"}):
            result = self.result()
            result.recognition_metadata = metadata
            with self.assertRaises(ProvenanceError):
                adapt_result(result, PHONE, "s", self.registry)

    def test_non_pattern_bypass_and_pattern_idempotency(self):
        identity = self.phone.id
        for _ in range(3):
            protect_patterns(self.registry)
            self.assertFalse(hasattr(self.phone, "patterns"))
            self.assertEqual(self.phone.id, identity)
            for producer in self.registry.recognizers:
                if isinstance(producer, PatternRecognizer):
                    producer.analyze("synthetic", producer.supported_entities)
                    for p in producer.patterns:
                        self.assertIsInstance(p.compiled_regex, _TimeoutMatcher)
                        self.assertNotIsInstance(p.compiled_regex._matcher, _TimeoutMatcher)

    def test_other_capabilities_remain_unsupported(self):
        service = L3AnalyzerService()
        for entity in ("ADDRESS",):
            with self.subTest(entity=entity), self.assertRaises(UnsupportedCapabilityError):
                service.analyze("", "s", entities=[entity])
        with self.assertRaises(UnsupportedCapabilityError):
            service.analyze(PHONE, "s", language="en")
