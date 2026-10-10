from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from privacy_proxy.l3.registry import (
    DEFAULT_ENTITIES,
    PRODUCER_TYPES,
    SUPPORTED_ENTITIES,
    build_registry,
    validate_registry,
)

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "address_contract_cases.json"


def _load_cases() -> list[dict[str, Any]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


def _load_address_class() -> type[Any]:
    module_name = "privacy_proxy.l3.address_recognizer"
    spec = importlib.util.find_spec(module_name)

    if spec is None:
        pytest.fail(
            "EXPECTED_RED_ADDRESS_MODULE_MISSING",
            pytrace=False,
        )

    module = importlib.import_module(module_name)
    address_class = getattr(module, "AddressRecognizer", None)

    if address_class is None:
        pytest.fail(
            "EXPECTED_RED_ADDRESS_CLASS_MISSING",
            pytrace=False,
        )

    return address_class


def test_frozen_matrix_shape() -> None:
    cases = _load_cases()

    positives = [case for case in cases if case["expected_l3_address"] is True]

    negatives = [case for case in cases if case["expected_l3_address"] is False]

    boundaries = [case for case in cases if str(case["id"]).startswith("B")]

    ids = [str(case["id"]) for case in cases]

    assert len(cases) == 26
    assert len(positives) == 14
    assert len(negatives) == 12
    assert len(boundaries) == 5
    assert len(ids) == len(set(ids))


def test_address_module_and_class_contract() -> None:
    address_class = _load_address_class()

    producer = address_class(
        supported_language="ko",
    )

    assert producer.name == "AddressRecognizer"
    assert producer.supported_entities == ["ADDRESS"]
    assert producer.supported_language == "ko"
    assert isinstance(producer.id, str)
    assert producer.id.strip()


def test_phase1_registry_transition_contract() -> None:
    if "ADDRESS" not in PRODUCER_TYPES:
        pytest.fail(
            "EXPECTED_RED_ADDRESS_PRODUCER_NOT_REGISTERED",
            pytrace=False,
        )

    address_class = _load_address_class()

    assert PRODUCER_TYPES["ADDRESS"] is address_class

    assert "ADDRESS" in SUPPORTED_ENTITIES
    assert "ADDRESS" in DEFAULT_ENTITIES

    assert len(PRODUCER_TYPES) == 13
    assert len(SUPPORTED_ENTITIES) == 13
    assert len(DEFAULT_ENTITIES) == 13

    registry = build_registry()
    producers = validate_registry(registry)

    assert set(producers) == set(SUPPORTED_ENTITIES)
    assert type(producers["ADDRESS"]) is address_class
    assert producers["ADDRESS"].name == "AddressRecognizer"
    assert producers["ADDRESS"].supported_language == "ko"


def test_default_inclusion_is_preserved() -> None:
    assert "ADDRESS" in DEFAULT_ENTITIES
    assert len(DEFAULT_ENTITIES) == 13
