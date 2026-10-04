"""Synthetic EMAIL configuration/provenance tests; no live address data."""

import unittest
from hashlib import sha256
from unittest.mock import patch

from presidio_analyzer import RecognizerResult
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.email_validation import (
    BUNDLED_SHA256,
    EmailConfigurationError,
    _snapshot_bytes,
    configure_email,
    validate_email_configuration,
)
from privacy_proxy.l3.provenance import ProvenanceError
from privacy_proxy.l3.registry import RegistryConfigurationError, build_registry, validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError
from privacy_proxy.l3.timeout_guard import (
    L3DependencyTimeoutError,
    TimeoutCallable,
    protect_callable,
)
from privacy_proxy.schemas import DetectionTier

EMAIL = "Audit+tag@Example.com"


class EmailUnitTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.email = validate_registry(self.registry)["EMAIL_ADDRESS"]

    def result(self, value=EMAIL, score=1.0):
        return RecognizerResult(
            "EMAIL_ADDRESS",
            0,
            len(value),
            score,
            recognition_metadata={
                "recognizer_name": self.email.name,
                "recognizer_identifier": self.email.id,
            },
        )

    def test_exact_eight_unique_email_identity(self):
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
            },
        )
        self.assertIs(type(self.email), EmailRecognizer)
        self.assertEqual(self.email.name, "EmailRecognizer")
        self.assertEqual(self.email.supported_language, "ko")
        self.assertEqual(
            sum("EMAIL_ADDRESS" in r.supported_entities for r in self.registry.recognizers), 1
        )

    def test_duplicate_email_rejected(self):
        self.registry.recognizers.append(self.email)
        with self.assertRaisesRegex(RegistryConfigurationError, "DUPLICATE"):
            validate_registry(self.registry)

    def test_snapshot_pinned(self):
        self.assertEqual(sha256(_snapshot_bytes()).hexdigest().upper(), BUNDLED_SHA256)

    def test_snapshot_missing_or_mismatch_fails_initialization(self):
        for kwargs in (
            {"return_value": b"wrong"},
            {"side_effect": FileNotFoundError("PRIVATE_MARKER")},
        ):
            with (
                self.subTest(kwargs=tuple(kwargs)),
                patch("privacy_proxy.l3.email_validation._snapshot_bytes", **kwargs),
            ):
                with self.assertRaises(L3RuntimeError) as caught:
                    L3AnalyzerService()
                self.assertNotIn("PRIVATE_MARKER", str(caught.exception))

    def test_version_mismatch_fails_initialization(self):
        with (
            patch("privacy_proxy.l3.email_validation.metadata.version", return_value="wrong"),
            self.assertRaises(L3RuntimeError),
        ):
            L3AnalyzerService()

    def test_configuration_mutation_rejected(self):
        extractor = self.email._email_validation._extractor
        for key, value in (
            ("suffix_list_urls", ("https://invalid.test",)),
            ("fallback_to_snapshot", False),
            ("include_psl_private_domains", True),
            ("extra_suffixes", ("invalid",)),
        ):
            with (
                self.subTest(key=key),
                patch.object(extractor, key, value),
                self.assertRaises(EmailConfigurationError),
            ):
                validate_registry(self.registry)
        with (
            patch.object(extractor._cache, "enabled", True),
            self.assertRaises(EmailConfigurationError),
        ):
            validate_registry(self.registry)
        with (
            patch.object(self.email, "validate_result", lambda value: True),
            self.assertRaises(EmailConfigurationError),
        ):
            validate_registry(self.registry)

    def test_guard_idempotent_and_identity_unchanged(self):
        identity = (type(self.email), self.email.name, self.email.id)
        guard = self.email.validate_result
        for _ in range(5):
            configure_email(self.email)
            self.assertIs(self.email.validate_result, guard)
            self.assertIs(protect_callable(guard), guard)
        self.assertIsInstance(guard, TimeoutCallable)
        self.assertNotIsInstance(guard.callback, TimeoutCallable)
        self.assertEqual(identity, (type(self.email), self.email.name, self.email.id))

    def test_callable_timeout_is_not_timeout_subclass(self):
        def fail(text):
            raise TimeoutError("PRIVATE_MARKER")

        with self.assertRaises(L3DependencyTimeoutError) as caught:
            protect_callable(fail)(EMAIL)
        self.assertNotIsInstance(caught.exception, TimeoutError)
        self.assertEqual(str(caught.exception), "L3_DEPENDENCY_TIMEOUT")
        self.assertTrue(caught.exception.__suppress_context__)

    def test_tier_requires_full_pattern_and_validation_not_score(self):
        for score in (0.0, 0.5, 1.0):
            d = adapt_result(self.result(score=score), EMAIL, "seg-email", self.registry)
            self.assertIs(d.tier, DetectionTier.RULE_ANCHORED)
            self.assertEqual(d.source, "EmailRecognizer")
            self.assertIsNone(d.confidence)
            self.assertEqual(d.normalized, EMAIL)
        for value in ("prefix " + EMAIL, "audit@@example.com", "audit@example.invalid"):
            with self.subTest(value=value), self.assertRaises(ProvenanceError):
                adapt_result(self.result(value), value, "s", self.registry)

    def test_metadata_conflict_fails(self):
        for metadata in (
            {"recognizer_name": "email_validation"},
            {"recognizer_identifier": "wrong"},
        ):
            r = self.result()
            r.recognition_metadata = metadata
            with self.assertRaises(ProvenanceError):
                adapt_result(r, EMAIL, "s", self.registry)

    def test_no_global_validator_replacement_or_shared_extractor(self):
        other = EmailRecognizer()
        self.assertIs(other.validate_result.__func__, EmailRecognizer.validate_result)
        second = validate_registry(build_registry())["EMAIL_ADDRESS"]
        self.assertIsNot(
            self.email._email_validation._extractor, second._email_validation._extractor
        )
        validate_email_configuration(second)
