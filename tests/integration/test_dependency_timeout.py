"""Actual installed PatternRecognizer timeout-path regression, no disk patches."""

import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from threading import Barrier
from unittest.mock import Mock, patch

from privacy_proxy.l3.registry import validate_registry
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError
from tests.fixtures import BRN_INVALID, BRN_VALID, PASSPORT

# Frozen pattern subset; PHONE parser failure paths have separate regressions.
PATTERN_ENTITIES = ("KR_RRN", "KR_FRN", "KR_PASSPORT", "KR_DRIVER_LICENSE", "KR_BRN")


@contextmanager
def replace_matcher(pattern, matcher):
    original = pattern.compiled_regex
    pattern.compiled_regex = matcher
    try:
        yield
    finally:
        pattern.compiled_regex = original


@contextmanager
def timeout_patterns(service, entity, lazy=False):
    producer = validate_registry(service._analyzer.registry)[entity]

    def lazy_failure(*args, **kwargs):
        yield from ()
        raise TimeoutError("SYNTHETIC_PRIVATE_ERROR")

    with ExitStack() as stack:
        for pattern in producer.patterns:
            matcher = Mock()
            if lazy:
                matcher.finditer.side_effect = lazy_failure
            else:
                matcher.finditer.side_effect = TimeoutError("SYNTHETIC_PRIVATE_ERROR")
            stack.enter_context(replace_matcher(pattern, matcher))
            stack.enter_context(
                patch.object(pattern, "compiled_with_flags", producer.global_regex_flags)
            )
        yield


class TimeoutRegressionTests(unittest.TestCase):
    def setUp(self):
        self.service = L3AnalyzerService()

    def test_brn_only_timeout_is_explicit_failure(self):
        with (
            timeout_patterns(self.service, "KR_BRN"),
            self.assertRaises(L3DependencyTimeoutError) as caught,
        ):
            self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])
        self.assertEqual(str(caught.exception), "L3_DEPENDENCY_TIMEOUT")
        self.assertNotIn(BRN_VALID, str(caught.exception))

    def test_successful_other_entity_cannot_escape_as_partial_output(self):
        registry = self.service._analyzer.registry
        producers = validate_registry(registry)
        # Force passport to run successfully before the injected BRN failure.
        registry.recognizers = [producers["KR_PASSPORT"]] + [
            p for e, p in producers.items() if e != "KR_PASSPORT"
        ]
        passport = producers["KR_PASSPORT"]
        with (
            patch.object(registry, "get_recognizers", return_value=[passport, producers["KR_BRN"]]),
            timeout_patterns(self.service, "KR_BRN"),
            patch.object(passport, "analyze", wraps=passport.analyze) as successful,
            patch("privacy_proxy.l3.service.adapt_result") as adapter,
        ):
            with self.assertRaises(L3DependencyTimeoutError):
                self.service.analyze(
                    PASSPORT + " | " + BRN_VALID, "s", entities=["KR_PASSPORT", "KR_BRN"]
                )
            successful.assert_called_once()
            adapter.assert_not_called()

    def test_normal_no_match(self):
        self.assertEqual(self.service.analyze("no identifier", "s", entities=["KR_BRN"]), [])

    def test_normal_valid_brn(self):
        self.assertEqual(len(self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])), 1)

    def test_normal_checksum_rejection(self):
        self.assertEqual(self.service.analyze(BRN_INVALID, "s", entities=["KR_BRN"]), [])

    def test_all_five_producers_eager_and_lazy_timeouts(self):
        for entity in PATTERN_ENTITIES:
            for lazy in (False, True):
                with (
                    self.subTest(entity=entity, lazy=lazy),
                    timeout_patterns(self.service, entity, lazy),
                    self.assertRaises(L3DependencyTimeoutError),
                ):
                    self.service.analyze("synthetic", "s", entities=[entity])

    def test_timeout_after_a_match_never_returns_that_match(self):
        self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])
        producer = validate_registry(self.service._analyzer.registry)["KR_BRN"]
        pattern = producer.patterns[0]
        real = pattern.compiled_regex

        def partial_then_timeout(*args, **kwargs):
            yield next(real.finditer(*args, **kwargs))
            raise TimeoutError("SYNTHETIC_PRIVATE_ERROR")

        matcher = Mock()
        matcher.finditer.side_effect = partial_then_timeout
        with replace_matcher(pattern, matcher), self.assertRaises(L3DependencyTimeoutError):
            self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])

    def test_recompilation_remains_protected(self):
        _producer = validate_registry(self.service._analyzer.registry)["KR_BRN"]
        matcher = Mock()
        matcher.finditer.side_effect = TimeoutError("SYNTHETIC_PRIVATE_ERROR")
        with (
            patch("presidio_analyzer.pattern_recognizer.re.compile", return_value=matcher),
            self.assertRaises(L3DependencyTimeoutError),
        ):
            self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])

    def test_pattern_caches_are_not_shared_across_services_or_builtins(self):
        other = L3AnalyzerService()
        one = validate_registry(self.service._analyzer.registry)
        two = validate_registry(other._analyzer.registry)
        for entity in PATTERN_ENTITIES:
            for a, b, original in zip(
                one[entity].patterns,
                two[entity].patterns,
                type(one[entity]).PATTERNS,
                strict=False,
            ):
                self.assertIsNot(a, b)
                self.assertIsNot(a, original)
                self.assertEqual(a.to_dict(), original.to_dict())

    def test_same_service_concurrent_timeout_and_success_are_isolated(self):
        self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])
        producer = validate_registry(self.service._analyzer.registry)["KR_BRN"]
        pattern = producer.patterns[0]
        real = pattern.compiled_regex
        rendezvous = Barrier(2)

        def concurrent_finditer(text, **kwargs):
            rendezvous.wait(timeout=10)
            if text.startswith("timeout:"):
                raise TimeoutError("SYNTHETIC_PRIVATE_ERROR")
            return real.finditer(text, **kwargs)

        matcher = Mock()
        matcher.finditer.side_effect = concurrent_finditer
        with replace_matcher(pattern, matcher), ThreadPoolExecutor(max_workers=2) as pool:
            failed = pool.submit(
                self.service.analyze, "timeout: " + BRN_VALID, "A", entities=["KR_BRN"]
            )
            passed = pool.submit(
                self.service.analyze, "success: " + BRN_VALID, "B", entities=["KR_BRN"]
            )
            with self.assertRaises(L3DependencyTimeoutError):
                failed.result(timeout=15)
            result = passed.result(timeout=15)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].segment_id, "B")
        self.assertEqual(len(self.service.analyze(BRN_VALID, "C", entities=["KR_BRN"])), 1)

    def test_timeout_is_independent_of_logging_and_has_no_raw_logs(self):
        logger = logging.getLogger("presidio-analyzer")
        with timeout_patterns(self.service, "KR_BRN"), patch.object(logger, "warning") as warning:
            with self.assertRaises(L3DependencyTimeoutError) as caught:
                self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])
            warning.assert_not_called()
        self.assertNotIn("SYNTHETIC_PRIVATE_ERROR", str(caught.exception))
        with (
            timeout_patterns(self.service, "KR_BRN"),
            patch.object(logger, "disabled", True),
            self.assertRaises(L3DependencyTimeoutError),
        ):
            self.service.analyze(BRN_VALID, "s", entities=["KR_BRN"])
