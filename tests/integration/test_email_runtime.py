"""E01-E20: reserved example-domain fixtures, no real accounts or network."""

import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier
from unittest.mock import Mock, patch

import tldextract
from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NoOpNlpEngine
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from privacy_proxy.l3.email_validation import _EmailValidation, configure_email
from privacy_proxy.l3.registry import validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError, protect_patterns
from privacy_proxy.schemas import DetectionTier
from tests.fixtures import KEYS, PASSPORT
from tests.integration.test_dependency_timeout import replace_matcher, timeout_patterns

EMAIL = "audit@example.com"
CASES = (
    EMAIL,
    "audit@sub.example.com",
    "audit+tag@example.com",
    "audit@@example.com",
    "audit@example.invalid",
    "\uac80\uc0ac " + EMAIL + " \uc548\ub0b4",
)


class EmailIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.service = L3AnalyzerService()
        self.email = validate_registry(self.service._analyzer.registry)["EMAIL_ADDRESS"]

    def detect(self, text, service=None):
        out = (service or self.service).analyze(text, "seg-email", entities=["EMAIL_ADDRESS"])
        for d in out:
            self.assertEqual(set(d.model_dump()), KEYS)
            self.assertEqual(d.entity_type, "EMAIL_ADDRESS")
            self.assertEqual(d.segment_id, "seg-email")
            self.assertEqual(d.source, "EmailRecognizer")
            self.assertIs(d.tier, DetectionTier.RULE_ANCHORED)
            self.assertIsNone(d.confidence)
            self.assertTrue(0 <= d.start_idx < d.end_idx <= len(text))
            self.assertEqual(text[d.start_idx : d.end_idx], d.original_value)
            self.assertEqual(d.normalized, d.original_value)
        return out

    def test_e01_normal(self):
        self.assertEqual(len(self.detect(EMAIL)), 1)

    def test_e02_subdomain(self):
        value = CASES[1]
        self.assertEqual(self.detect(value)[0].original_value, value)

    def test_e03_plus(self):
        value = CASES[2]
        self.assertEqual(self.detect(value)[0].original_value, value)

    def test_e04_invalid_syntax_and_no_match(self):
        self.assertEqual(self.detect(CASES[3]), [])
        self.assertEqual(self.detect("no address"), [])

    def test_e05_invalid_tld(self):
        self.assertEqual(self.detect(CASES[4]), [])

    def test_e06_korean_context(self):
        out = self.detect(CASES[5])
        self.assertEqual((out[0].start_idx, out[0].end_idx), (3, 20))

    def test_e07_prefix_local_part_boundary(self):
        value = "prefix." + EMAIL
        self.assertEqual(self.detect("<" + value + ">")[0].original_value, value)

    def test_e08_suffix_boundary(self):
        self.assertEqual(self.detect(EMAIL + ".")[0].original_value, EMAIL)
        self.assertEqual(self.detect(EMAIL + ".invalid"), [])

    def test_e09_matcher_immediate_timeout(self):
        with (
            timeout_patterns(self.service, "EMAIL_ADDRESS"),
            self.assertRaises(L3DependencyTimeoutError),
        ):
            self.detect(EMAIL)

    def test_e10_iterator_timeout_after_match(self):
        self.detect(EMAIL)
        p = self.email.patterns[0]
        real = p.compiled_regex

        def partial(*args, **kwargs):
            yield next(real.finditer(*args, **kwargs))
            raise TimeoutError("RAW_EMAIL_MARKER")

        matcher = Mock()
        matcher.finditer.side_effect = partial
        with replace_matcher(p, matcher), self.assertRaises(L3DependencyTimeoutError):
            self.detect(EMAIL)

    def test_e11_first_validator_timeout_no_warning_leak(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = Capture()
        logger = logging.getLogger("presidio-analyzer")
        logger.addHandler(handler)
        try:
            with (
                patch.object(
                    _EmailValidation, "__call__", side_effect=TimeoutError("RAW_EMAIL_MARKER")
                ),
                self.assertRaises(L3DependencyTimeoutError) as caught,
            ):
                self.detect(EMAIL)
            self.assertNotIn("RAW_EMAIL_MARKER", str(caught.exception))
            self.assertFalse(any(r.levelno >= logging.WARNING for r in records))
            self.assertNotIn(
                "RAW_EMAIL_MARKER", "\n".join(logging.Formatter().format(r) for r in records)
            )
        finally:
            logger.removeHandler(handler)

    def test_e12_validator_timeout_after_prior_success(self):
        with patch.object(
            _EmailValidation, "__call__", side_effect=[True, TimeoutError("RAW_EMAIL_MARKER")]
        ) as validator:
            with self.assertRaises(L3DependencyTimeoutError):
                self.detect(EMAIL + " second@example.com")
            self.assertEqual(validator.call_count, 2)

    def test_e13_validator_runtime_error_sanitized(self):
        with (
            patch.object(
                _EmailValidation, "__call__", side_effect=RuntimeError("RAW_EMAIL_MARKER")
            ),
            self.assertRaises(L3RuntimeError) as caught,
        ):
            self.detect(EMAIL)
        self.assertNotIn("RAW_EMAIL_MARKER", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_e14_extractor_failures(self):
        for error, expected in (
            (TimeoutError, L3DependencyTimeoutError),
            (RuntimeError, L3RuntimeError),
        ):
            with (
                self.subTest(error=error),
                patch.object(
                    tldextract.TLDExtract, "__call__", side_effect=error("RAW_EMAIL_MARKER")
                ),
            ):
                with self.assertRaises(expected) as caught:
                    self.detect(EMAIL)
                self.assertNotIn("RAW_EMAIL_MARKER", str(caught.exception))

    def test_e15_no_remote_fetch_or_global_extractor(self):
        with (
            patch(
                "requests.sessions.Session.request", side_effect=AssertionError("NETWORK")
            ) as network,
            patch(
                "tldextract.extract", side_effect=AssertionError("GLOBAL_EXTRACT")
            ) as global_extract,
        ):
            service = L3AnalyzerService()
            self.assertEqual(len(self.detect(EMAIL, service)), 1)
            network.assert_not_called()
            global_extract.assert_not_called()

    def test_e16_cache_disabled_repeated_initialization(self):
        with ExitStack() as stack:
            forbidden = [
                stack.enter_context(patch(target, side_effect=AssertionError("CACHE_OR_UPDATE")))
                for target in (
                    "tldextract.cache.DiskCache.get",
                    "tldextract.cache.DiskCache.set",
                    "tldextract.cache.DiskCache.cached_fetch_url",
                    "tldextract.cache._make_dir",
                    "tldextract.TLDExtract.update",
                )
            ]
            outputs = []
            for _ in range(3):
                service = L3AnalyzerService()
                outputs.append([d.model_dump() for d in self.detect(EMAIL, service)])
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[1], outputs[2])
            for mock in forbidden:
                mock.assert_not_called()

    def test_e17_en_ko_equivalence(self):
        results = []
        for language in ("en", "ko"):
            producer = EmailRecognizer(supported_language=language)
            configure_email(producer)
            registry = RecognizerRegistry(recognizers=[producer], supported_languages=[language])
            protect_patterns(registry)
            engine = AnalyzerEngine(
                registry=registry,
                supported_languages=[language],
                nlp_engine=NoOpNlpEngine(models=[{"lang_code": language, "model_name": ""}]),
            )
            rows = []
            for value in CASES:
                rows.append(
                    [
                        (
                            r.start,
                            r.end,
                            r.score,
                            r.analysis_explanation.validation_result,
                            r.recognition_metadata["recognizer_name"],
                        )
                        for r in engine.analyze(
                            value,
                            language,
                            entities=["EMAIL_ADDRESS"],
                            return_decision_process=True,
                        )
                    ]
                )
            results.append(rows)
        self.assertEqual(results[0], results[1])

    def test_e18_identity_case_preservation_default_capability(self):
        value = "Audit+TAG@Example.COM"
        self.assertEqual(self.detect(value)[0].original_value, value)
        self.assertEqual(len(self.service.analyze(value, "s")), 1)

    def test_e19_other_success_before_email_failure_is_atomic(self):
        registry = self.service._analyzer.registry
        passport = validate_registry(registry)["KR_PASSPORT"]
        with (
            patch.object(registry, "get_recognizers", return_value=[passport, self.email]),
            patch.object(passport, "analyze", wraps=passport.analyze) as success,
            patch.object(
                _EmailValidation, "__call__", side_effect=TimeoutError("RAW_EMAIL_MARKER")
            ),
            patch("privacy_proxy.l3.service.adapt_result") as adapter,
        ):
            with self.assertRaises(L3DependencyTimeoutError):
                self.service.analyze(
                    PASSPORT + " " + EMAIL, "s", entities=["KR_PASSPORT", "EMAIL_ADDRESS"]
                )
            success.assert_called_once()
            adapter.assert_not_called()

    def test_e20_cross_request_isolation(self):
        barrier = Barrier(2)
        original = _EmailValidation.__call__

        def injected(validator, text):
            # The successful raw slice is revalidated by the tier adapter.
            # Only the first recognizer calls rendezvous.
            if text.startswith("fail@") or not getattr(local, "passed", False):
                barrier.wait(timeout=5)
                local.passed = True
            if text.startswith("fail@"):
                raise TimeoutError("RAW_EMAIL_MARKER")
            return original(validator, text)

        from threading import local as local_type

        local = local_type()

        def run(value):
            try:
                return len(self.detect(value))
            except L3DependencyTimeoutError:
                return "TIMEOUT"

        with (
            patch.object(_EmailValidation, "__call__", injected),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            a = pool.submit(run, "fail@example.com")
            b = pool.submit(run, "ok@example.com")
            self.assertEqual(a.result(), "TIMEOUT")
            self.assertEqual(b.result(), 1)

    def test_no_raw_email_runtime_logs(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = Capture()
        logger = logging.getLogger()
        logger.addHandler(handler)
        try:
            self.detect(EMAIL)
            with (
                patch.object(_EmailValidation, "__call__", side_effect=RuntimeError(EMAIL)),
                self.assertRaises(L3RuntimeError),
            ):
                self.detect(EMAIL)
            self.assertNotIn(EMAIL, "\n".join(logging.Formatter().format(r) for r in records))
        finally:
            logger.removeHandler(handler)
