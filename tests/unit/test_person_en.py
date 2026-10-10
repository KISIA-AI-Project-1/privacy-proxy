"""R6 PERSON_EN unit contract.

This suite intentionally begins RED.

Before implementation only the bootstrap module-existence test is
expected to fail. Remaining tests stay blocked until the production
module exists.
"""

from importlib import import_module
from importlib.util import find_spec

import pytest

from privacy_proxy.l3.registry import PRODUCER_TYPES, build_registry
from privacy_proxy.l3.tier_mapping import tier_for
from privacy_proxy.schemas import DetectionTier

MODULE_NAME = "privacy_proxy.l3.person_en_recognizer"
MODULE_PRESENT = find_spec(MODULE_NAME) is not None

requires_person_en_module = pytest.mark.skipif(
    not MODULE_PRESENT,
    reason="blocked until PersonEnRecognizer implementation exists",
)


def _recognizer_class():
    module = import_module(MODULE_NAME)
    return module.PersonEnRecognizer


def test_r6_red_person_en_module_exists() -> None:
    assert MODULE_PRESENT, "RED_PERSON_EN_MODULE_MISSING"


@requires_person_en_module
def test_person_en_recognizer_identity() -> None:
    producer = _recognizer_class()()

    assert producer.name == "PersonEnRecognizer"
    assert producer.supported_entities == ["PERSON_EN"]
    assert producer.supported_language == "ko"


@requires_person_en_module
def test_person_en_registry_uses_exact_producer_type() -> None:
    recognizer_class = _recognizer_class()

    assert PRODUCER_TYPES["PERSON_EN"] is recognizer_class

    registry = build_registry()

    producers = [
        producer
        for producer in registry.recognizers
        if producer.supported_entities == ["PERSON_EN"]
    ]

    assert len(producers) == 1
    assert type(producers[0]) is recognizer_class
    assert producers[0].supported_language == "ko"


@requires_person_en_module
def test_person_en_tier_is_model() -> None:
    producer = _recognizer_class()()

    assert (
        tier_for(
            producer,
            "PERSON_EN",
            "John Smith",
        )
        is DetectionTier.MODEL
    )
