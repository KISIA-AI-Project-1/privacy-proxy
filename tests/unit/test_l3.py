import unittest
from unittest.mock import patch

from presidio_analyzer import RecognizerResult

from privacy_proxy.contracts.detection import DetectionValidationError
from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3.analyzer_factory import build_analyzer
from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.provenance import ProvenanceError
from privacy_proxy.l3.registry import (
    SUPPORTED_ENTITIES,
    RegistryConfigurationError,
    build_registry,
    validate_registry,
)
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError, UnsupportedCapabilityError
from tests.fixtures import BRN_INVALID, BRN_VALID, LICENSE_VALID, PASSPORT, RRN_VALID


class RegistryTests(unittest.TestCase):
    def test_exact_seven_unique_and_ko(self):
        registry = build_registry()
        self.assertEqual(set(validate_registry(registry)), set(SUPPORTED_ENTITIES))
        self.assertEqual(len(registry.recognizers), 7)
        self.assertEqual(registry.supported_languages, ["ko"])

    def test_duplicate_rejected(self):
        registry = build_registry()
        registry.recognizers.append(registry.recognizers[-1])
        with self.assertRaisesRegex(RegistryConfigurationError, "DUPLICATE"):
            validate_registry(registry)

    def test_missing_rejected(self):
        registry = build_registry()
        registry.recognizers.pop()
        with self.assertRaisesRegex(RegistryConfigurationError, "INCOMPLETE"):
            validate_registry(registry)

    def test_language_rejected(self):
        registry = build_registry()
        registry.supported_languages = ["en"]
        with self.assertRaises(RegistryConfigurationError):
            validate_registry(registry)

    def test_factory_explicit_noop_ko(self):
        analyzer = build_analyzer()
        self.assertEqual(analyzer.supported_languages, ["ko"])
        self.assertEqual(analyzer.nlp_engine.get_supported_languages(), ["ko"])
        self.assertFalse(analyzer.log_decision_process)
        self.assertEqual(analyzer.nlp_engine.get_supported_entities(), [])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

    def result(self, entity, value, score=0.1):
        producer = validate_registry(self.registry)[entity]
        return RecognizerResult(
            entity,
            2,
            2 + len(value),
            score,
            recognition_metadata={
                "recognizer_name": producer.name,
                "recognizer_identifier": producer.id,
            },
        )

    def test_offsets_identity_confidence_source(self):
        result = self.result("KR_PASSPORT", PASSPORT, 1.0)
        d = adapt_result(result, "!!" + PASSPORT + "!", "segment", self.registry)
        self.assertEqual((d.start_idx, d.end_idx), (result.start, result.end))
        self.assertEqual(d.original_value, PASSPORT)
        self.assertEqual(d.normalized, PASSPORT)
        self.assertIsNone(d.confidence)
        self.assertEqual(d.source, "KrPassportRecognizer")
        self.assertEqual(d.tier, "RULE_ANCHORED")

    def test_actual_validation_required(self):
        for entity, value in [("KR_BRN", BRN_VALID), ("KR_DRIVER_LICENSE", LICENSE_VALID)]:
            d = adapt_result(self.result(entity, value, 0.01), "!!" + value, "s", self.registry)
            self.assertEqual(d.tier, "DETERMINISTIC")
        with self.assertRaisesRegex(ProvenanceError, "VALIDATION"):
            adapt_result(
                self.result("KR_BRN", BRN_INVALID, 1.0), "!!" + BRN_INVALID, "s", self.registry
            )

    def test_rrn_score_does_not_determine_tier(self):
        for score in [0.5, 1.0]:
            d = adapt_result(
                self.result("KR_RRN", RRN_VALID, score), "!!" + RRN_VALID, "s", self.registry
            )
            self.assertIsNone(d.tier)

    def test_missing_metadata_unique_producer_fallback(self):
        result = self.result("KR_PASSPORT", PASSPORT)
        result.recognition_metadata = None
        self.assertEqual(
            adapt_result(result, "!!" + PASSPORT, "s", self.registry).source, "KrPassportRecognizer"
        )

    def test_empty_unknown_or_conflicting_provenance_fails(self):
        for metadata in [
            {"recognizer_name": ""},
            {"recognizer_name": "unknown"},
            {"recognizer_identifier": "unknown"},
            {"recognizer_name": None},
        ]:
            result = self.result("KR_PASSPORT", PASSPORT)
            result.recognition_metadata = metadata
            with self.assertRaises(ProvenanceError):
                adapt_result(result, "!!" + PASSPORT, "s", self.registry)
        result = RecognizerResult("UNKNOWN", 0, 1, 1.0)
        with self.assertRaises(ProvenanceError):
            adapt_result(result, "x", "s", self.registry)

    def test_out_of_bounds_fails(self):
        result = self.result("KR_PASSPORT", PASSPORT)
        result.end = 999
        with self.assertRaises(DetectionValidationError):
            adapt_result(result, "!!" + PASSPORT, "s", self.registry)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = L3AnalyzerService()

    def test_unsupported_entity_and_language(self):
        for entities in [["LOCATION"], ["KR_BRN", "AGE"], "KR_BRN", [None]]:
            with self.assertRaises(UnsupportedCapabilityError):
                self.service.analyze("", "s", entities=entities)
        with self.assertRaises(UnsupportedCapabilityError):
            self.service.analyze("", "s", language="en")

    def test_invalid_inputs(self):
        for raw, segment in [(None, "s"), ("x", None), ("x", ""), ("x", " ")]:
            with self.assertRaises(ValueError):
                self.service.analyze(raw, segment)
        with self.assertRaises(TypeError):
            self.service.analyze("x")

    def test_explicit_empty_entities(self):
        self.assertEqual(self.service.analyze(BRN_VALID, "s", entities=[]), [])

    def test_registry_mutation_fails(self):
        self.service._analyzer.registry.recognizers.pop()
        with self.assertRaises(RegistryConfigurationError):
            self.service.analyze("", "s")

    def test_initialization_failure_is_error(self):
        with (
            patch("privacy_proxy.l3.service.build_analyzer", side_effect=RuntimeError("secret")),
            self.assertRaisesRegex(L3RuntimeError, "INITIALIZATION") as caught,
        ):
            L3AnalyzerService()
        self.assertNotIn("secret", str(caught.exception))

    def test_runtime_failure_is_error_without_raw_value(self):
        with (
            patch.object(self.service._analyzer, "analyze", side_effect=ValueError(BRN_VALID)),
            self.assertRaises(L3RuntimeError) as caught,
        ):
            self.service.analyze(BRN_VALID, "s")
        self.assertNotIn(BRN_VALID, str(caught.exception))

    def test_producer_output_rechecks_raw_span(self):
        detections = self.service.analyze(PASSPORT, "s", entities=["KR_PASSPORT"])
        output = L3Output(PASSPORT, tuple(detections))
        self.assertNotIn(PASSPORT, repr(output))
        with self.assertRaises(DetectionValidationError):
            L3Output("different", tuple(detections))
