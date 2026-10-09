"""Synthetic example-number fixtures from step7a5_1c1_phone_case_manifest.json.
No experimental script imports, network calls or real personal data.
"""

import importlib
import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from presidio_analyzer.predefined_recognizers import PhoneRecognizer

from privacy_proxy.l3.registry import validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError
from privacy_proxy.schemas import DetectionTier
from tests.fixtures import KEYS, PASSPORT

PHONE = "010-2000-0000"
INTERNATIONAL = "+82 10-2000-0000"
US_CONTROL = "+1 201-555-0123"
PHONE_MODULE = importlib.import_module(PhoneRecognizer.__module__)


class PhoneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.service = L3AnalyzerService()

    def detect(self, value, entities=("PHONE_NUMBER",)):
        raw = "\uac80\uc0ac: " + value + " !"
        out = self.service.analyze(raw, "seg-phone", entities=entities)
        for d in out:
            self.assertEqual(set(d.model_dump()), KEYS)
            self.assertIsNone(d.confidence)
            self.assertEqual(d.segment_id, "seg-phone")
            self.assertTrue(0 <= d.start_idx < d.end_idx <= len(raw))
            self.assertEqual(raw[d.start_idx : d.end_idx], d.original_value)
            self.assertEqual(d.normalized, d.original_value)
            if d.entity_type == "PHONE_NUMBER":
                self.assertEqual(d.source, "PhoneRecognizer")
                self.assertIs(d.tier, DetectionTier.RULE_ANCHORED)
                self.assertEqual(d.original_value, value)
                self.assertEqual((d.start_idx, d.end_idx), (4, 4 + len(value)))
        return out

    def test_p01_domestic_hyphenated(self):
        self.assertEqual(len(self.detect(PHONE)), 1)

    def test_p02_domestic_compact(self):
        self.assertEqual(len(self.detect("01020000000")), 1)

    def test_p03_international_kr(self):
        for value in (INTERNATIONAL, "+821020000000"):
            with self.subTest(value_format=len(value)):
                self.assertEqual(len(self.detect(value)), 1)

    def test_p04_separator_variation(self):
        self.assertEqual(len(self.detect(PHONE.replace("-", " "))), 1)

    def test_p05_invalid_and_normal_no_match(self):
        for value in ("123", "no phone here"):
            self.assertEqual(self.detect(value), [])

    def test_p06_kr_region_is_not_country_allowlist(self):
        self.assertEqual(len(self.detect(US_CONTROL)), 1)

    def test_p07_digit_and_embedded_boundaries(self):
        for value in ("9" + PHONE, PHONE + "9", "abc" + PHONE + "xyz"):
            self.assertEqual(self.detect(value), [])

    def test_p08_matcher_and_parser_failures_are_explicit_private_errors(self):
        for method in ("PhoneNumberMatcher", "parse"):
            for exception in (TimeoutError, RuntimeError):
                with self.subTest(method=method, exception=exception.__name__):
                    with (
                        patch.object(
                            PHONE_MODULE.phonenumbers, method, side_effect=exception(PHONE)
                        ),
                        self.assertRaises(L3RuntimeError) as caught,
                    ):
                        self.service.analyze(PHONE, "s", entities=["PHONE_NUMBER"])
                    self.assertNotIn(PHONE, str(caught.exception))
                    self.assertTrue(caught.exception.__suppress_context__)

    def test_failure_after_other_entity_success_never_returns_partial(self):
        registry = self.service._analyzer.registry
        producers = validate_registry(registry)
        passport, phone = producers["KR_PASSPORT"], producers["PHONE_NUMBER"]
        for exception in (TimeoutError, RuntimeError):
            with (
                patch.object(registry, "get_recognizers", return_value=[passport, phone]),
                patch.object(passport, "analyze", wraps=passport.analyze) as successful,
                patch.object(
                    PHONE_MODULE.phonenumbers, "PhoneNumberMatcher", side_effect=exception(PHONE)
                ),
                patch("privacy_proxy.l3.service.adapt_result") as adapter,
            ):
                with self.assertRaises(L3RuntimeError):
                    self.service.analyze(
                        PASSPORT + " | " + PHONE, "s", entities=["KR_PASSPORT", "PHONE_NUMBER"]
                    )
                successful.assert_called_once()
                adapter.assert_not_called()

    def test_failure_after_phone_match_never_returns_partial(self):
        real = PHONE_MODULE.phonenumbers.PhoneNumberMatcher

        def partial(*args, **kwargs):
            yield next(iter(real(*args, **kwargs)))
            raise TimeoutError(PHONE)

        with (
            patch.object(PHONE_MODULE.phonenumbers, "PhoneNumberMatcher", side_effect=partial),
            self.assertRaises(L3RuntimeError),
        ):
            self.service.analyze(PHONE, "s", entities=["PHONE_NUMBER"])

    def test_p09_default_subset_includes_phone(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        ner = SimpleNamespace(labels=("LC",))
        model = Mock(side_effect=lambda text: SimpleNamespace(text=text, ents=()))
        model.lang = "ko"
        model.meta = {"lang": "ko", "name": "core_news_lg", "version": "3.8.0"}
        model.pipe_names = ["ner"]
        model.pipe_labels = {"ner": ["LC"]}
        model.has_pipe.side_effect = lambda name: name == "ner"
        model.get_pipe.side_effect = lambda name: ner if name == "ner" else None

        with patch("spacy.util.load_model", return_value=model):
            detections = self.detect(PHONE, entities=None)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].entity_type, "PHONE_NUMBER")

    def test_concurrent_failure_and_success_are_isolated(self):
        real = PHONE_MODULE.phonenumbers.PhoneNumberMatcher
        rendezvous = Barrier(2)

        def matcher(text, *args, **kwargs):
            # The exact-slice adapter recheck does not enter the barrier.
            if text.startswith(("FAIL: ", "OK: ")):
                rendezvous.wait(timeout=10)
                if text.startswith("FAIL: "):
                    raise TimeoutError(PHONE)
            return real(text, *args, **kwargs)

        with (
            patch.object(PHONE_MODULE.phonenumbers, "PhoneNumberMatcher", side_effect=matcher),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            fail = pool.submit(
                self.service.analyze, "FAIL: " + PHONE, "A", entities=["PHONE_NUMBER"]
            )
            good = pool.submit(self.service.analyze, "OK: " + PHONE, "B", entities=["PHONE_NUMBER"])
            with self.assertRaises(L3RuntimeError):
                fail.result(timeout=15)
            out = good.result(timeout=15)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].segment_id, "B")

    def test_no_raw_phone_in_runtime_logging(self):
        messages = []

        class Capture(logging.Handler):
            def emit(self, record):
                messages.append(self.format(record))

        logger = logging.getLogger("presidio-analyzer")
        old_level = logger.level
        handler = Capture()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            self.detect(PHONE)
            with (
                patch.object(
                    PHONE_MODULE.phonenumbers, "PhoneNumberMatcher", side_effect=RuntimeError(PHONE)
                ),
                self.assertRaises(L3RuntimeError),
            ):
                self.service.analyze(PHONE, "s", entities=["PHONE_NUMBER"])
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)
        self.assertFalse(any(PHONE in message for message in messages))
