"""Synthetic EMAIL configuration/provenance tests; no live address data."""

import unittest
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import regex
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
from tests.fixtures import KEYS

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

    def test_exact_nine_unique_email_identity(self):
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

    def assert_exact_email(self, raw, expected):
        results = self.email.analyze(text=raw, entities=["EMAIL_ADDRESS"])
        self.assertEqual(len(results), 1)
        result = results[0]
        start = raw.index(expected)
        self.assertEqual((result.start, result.end), (start, start + len(expected)))
        detection = adapt_result(result, raw, "seg-email-boundary", self.registry)
        self.assertEqual(set(detection.model_dump()), KEYS)
        self.assertEqual(detection.segment_id, "seg-email-boundary")
        self.assertTrue(0 <= detection.start_idx < detection.end_idx <= len(raw))
        self.assertEqual(raw[detection.start_idx : detection.end_idx], expected)
        self.assertEqual(detection.original_value, expected)
        self.assertEqual(detection.normalized, expected)
        self.assertEqual(detection.entity_type, "EMAIL_ADDRESS")
        self.assertEqual(detection.source, "EmailRecognizer")
        self.assertIsNone(detection.confidence)
        self.assertIs(detection.tier, DetectionTier.RULE_ANCHORED)

    def test_korean_attached_suffix_is_email_boundary(self):
        suffixes = (
            "\uc785\ub2c8\ub2e4",
            "\uc774\uc5d0\uc694",
            "\uc73c\ub85c",
            "\uc5d0\uc11c",
            "\uc774\uba74",
            "\uc740",
            "\uc774",
            "\uc744",
            "\ubb38\uc758\ub4dc\ub9bd\ub2c8\ub2e4",
            "\ud55c\uae00",
            "\uac00\ub098\ub2e4",
        )
        for email in ("test@example.com", "test@example.co.kr"):
            for suffix in suffixes:
                for prefix, ending in (("", ""), ("\uc548\ub0b4 \U0001f642 ", ".")):
                    raw = prefix + email + suffix + ending
                    with self.subTest(raw=raw):
                        self.assert_exact_email(raw, email)

    def test_unicode_domain_with_korean_suffix(self):
        for expected in (
            "test@\uc608\uc2dc.com",
            "test@b\u00fccher.de",
            "test@\uc608\uc2dc.co.kr",
            "test@xn--bcher-kva.de",
            "test@example.com\ud55c\uae00.com",
            "test@example.com\u00e9.fr",
        ):
            for prefix in ("", "\uc548\ub0b4 \U0001f642 "):
                raw = prefix + expected + "\uc785\ub2c8\ub2e4"
                with self.subTest(raw=raw):
                    self.assert_exact_email(raw, expected)

    def test_unicode_tld_baseline_and_korean_suffix(self):
        for tld in ("\ud55c\uad6d", "\ub2f7\ucef4", "\uc0bc\uc131", "\u4e2d\u56fd"):
            self.assertIn(tld, self.email._email_validation._extractor.tlds)
            for label in ("example", "\uc608\uc2dc"):
                expected = "test@" + label + "." + tld
                # The existing built-in pattern and pinned validator support
                # this full address before any Korean suffix correction.
                self.assertIsNotNone(
                    regex.fullmatch(
                        EmailRecognizer.PATTERNS[0].regex, expected, self.email.global_regex_flags
                    )
                )
                self.assertTrue(self.email.validate_result(expected))
                for suffix in ("", "\uc785\ub2c8\ub2e4", "\ubb38\uc758\ub4dc\ub9bd\ub2c8\ub2e4"):
                    with self.subTest(expected=expected, suffix=suffix):
                        self.assert_exact_email(expected + suffix, expected)

    def test_unicode_tld_continuation_is_not_truncated(self):
        for raw in (
            "test@example.\ud55c\uad6d\uc785\ub2c8\ub2e4.com",
            "test@example.\ud55c\uad6d\uc785\ub2c8\ub2e4-sub.com",
        ):
            with self.subTest(raw=raw):
                self.assert_exact_email(raw, raw)
                self.assertIsNone(
                    regex.search(self.email.patterns[-1].regex, raw, self.email.global_regex_flags)
                )
        for raw in (
            "test@example.\ud55c\uad6dabc",
            "test@example.\ud55c\uad6d123",
            "test@example.\ud55c\uad6d_abc",
            "test@example.\ud55c\uad6d-abc",
            "test@example.\ud55c\uad6d\uc785\ub2c8\ub2e4.invalid",
            "test@example..\ud55c\uad6d\uc785\ub2c8\ub2e4",
            "test@example.\uc5c6\ub294\ub3c4\uba54\uc778",
            "test@example.\uc5c6\ub294\ub3c4\uba54\uc778\uc785\ub2c8\ub2e4",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.email.analyze(raw, ["EMAIL_ADDRESS"]), [])

    def test_unicode_tld_authority_failure_fails_initialization(self):
        with (
            patch(
                "privacy_proxy.l3.email_validation.TLDExtract.tlds",
                new_callable=PropertyMock,
                side_effect=RuntimeError("PRIVATE_MARKER"),
            ),
            self.assertRaises(L3RuntimeError) as caught,
        ):
            L3AnalyzerService()
        self.assertNotIn("PRIVATE_MARKER", str(caught.exception))

    def test_unicode_domain_preservation_without_partial_detection(self):
        cases = (
            "test@\uc608\uc2dc.com",
            "test@b\u00fccher.de",
            "test@example.com\ud55c\uae00.com",
            "test@example.com\u00e9.fr",
            "test@example.com\ud55c\uae00-sub.com",
            "test@example.com\ud55c\uae00abc.com",
        )
        for value in cases:
            with self.subTest(value=value):
                self.assert_exact_email(value, value)

    def test_korean_fallback_does_not_match_unicode_domain_prefix(self):
        fallback = self.email.patterns[-1]
        for raw in (
            "test@example.com\ud55c\uae00.com",
            "test@example.com\u00e9.fr",
            "test@example.com\ud55c\uae00-sub.com",
            "test@example.com\ud55c\uae00abc.com",
            "test@example.com\ud55c\uae00.invalid",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(regex.search(fallback.regex, raw, self.email.global_regex_flags))

    def test_ascii_email_continuation_is_not_truncated(self):
        for raw in (
            "test@example.comabc",
            "test@example.comABC",
            "test@example.com123",
            "test@example.com_abc",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.email.analyze(raw, ["EMAIL_ADDRESS"]), [])

    def test_existing_email_behavior_preserved(self):
        cases = (
            ("test@example.com", "test@example.com"),
            ("test@example.company", "test@example.company"),
            ("test@xn--bcher-kva.de", "test@xn--bcher-kva.de"),
            ("test@example.xn--p1ai", "test@example.xn--p1ai"),
            ("test@sub.my-example.co.kr", "test@sub.my-example.co.kr"),
            ("test@my--example.com", "test@my--example.com"),
            ("test+tag@example.com", "test+tag@example.com"),
            ("First.Last+TAG@Example.COM", "First.Last+TAG@Example.COM"),
            ("test@example.com-", "test@example.com"),
            ("test@example.com+abc", "test@example.com"),
            ("test@example.com.", "test@example.com"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assert_exact_email(raw, expected)

    def test_malformed_email_and_unknown_suffix_rejected(self):
        for raw in (
            "test@example",
            "test@ example.com",
            "test@@example.com",
            "@example.com",
            "test@example.com-abc",
            "test@example.invalid",
            "test@example.com.invalid",
            "test@example..com",
            "test@example.com\ud55c\uae00.invalid",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.email.analyze(raw, ["EMAIL_ADDRESS"]), [])

    def test_korean_boundary_pattern_is_instance_local(self):
        global_patterns = EmailRecognizer.PATTERNS
        global_state = [vars(p).copy() for p in global_patterns]
        vanilla = EmailRecognizer()
        first, second = EmailRecognizer(), EmailRecognizer()
        identity = (type(first), first.name, first.id)
        configure_email(first)
        configure_email(second)
        self.assertEqual(len(first.patterns), len(global_patterns) + 1)
        self.assertIsNot(first.patterns, second.patterns)
        for index, original in enumerate(global_patterns):
            installed = first.patterns[index]
            self.assertEqual(
                (installed.name, installed.regex, installed.score),
                (original.name, original.regex, original.score),
            )
            self.assertIsNot(installed, original)
        for left, right in zip(first.patterns, second.patterns, strict=True):
            self.assertIsNot(left, right)
        for _ in range(2):
            configure_email(first)
            first.analyze("test@example.com\uc785\ub2c8\ub2e4", ["EMAIL_ADDRESS"])
            first.analyze("test@\uc608\uc2dc.com", ["EMAIL_ADDRESS"])
            first.analyze("test@\uc608\uc2dc.com\uc785\ub2c8\ub2e4", ["EMAIL_ADDRESS"])
            first.analyze("test@\uc608\uc2dc.\ud55c\uad6d\uc785\ub2c8\ub2e4", ["EMAIL_ADDRESS"])
        self.assertEqual(identity, (type(first), first.name, first.id))
        with patch.object(first.patterns[-1], "regex", "changed"):
            with self.assertRaises(EmailConfigurationError):
                validate_email_configuration(first)
            validate_email_configuration(second)
        self.assertIs(EmailRecognizer.PATTERNS, global_patterns)
        self.assertEqual([vars(p) for p in global_patterns], global_state)
        self.assertIs(vanilla.patterns, global_patterns)
        self.assertIs(EmailRecognizer().patterns, global_patterns)
