from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from privacy_proxy.l3.registry import SUPPORTED_ENTITIES
from privacy_proxy.l3.service import L3AnalyzerService, UnsupportedCapabilityError
from privacy_proxy.schemas import DetectionTier, ProxyContext

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "address_contract_cases.json"

ADDRESS_SUPPORTED_AT_COLLECTION = "ADDRESS" in SUPPORTED_ENTITIES


def _load_cases() -> list[dict[str, Any]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return list(payload["cases"])


CASES = _load_cases()

POSITIVE_CASES = [case for case in CASES if case["expected_l3_address"] is True]

NEGATIVE_CASES = [case for case in CASES if case["expected_l3_address"] is False]


@pytest.fixture(scope="module")
def service() -> L3AnalyzerService:
    return L3AnalyzerService()


@pytest.mark.parametrize(
    "case",
    POSITIVE_CASES,
    ids=lambda case: str(case["id"]),
)
def test_address_positive_runtime_contract(
    service: L3AnalyzerService,
    case: dict[str, Any],
) -> None:
    raw = str(case["text"])
    expected_span = str(case["expected_span"])
    segment_id = f"r7-s3-{case['id']}"

    try:
        detections = service.analyze(
            raw,
            segment_id,
            entities=["ADDRESS"],
        )
    except UnsupportedCapabilityError as exc:
        if str(exc) != "UNSUPPORTED_ENTITY":
            raise

        pytest.fail(
            f"EXPECTED_RED_ADDRESS_UNSUPPORTED:{case['id']}",
            pytrace=False,
        )

    assert len(detections) == 1

    detection = detections[0]

    expected_start = raw.index(expected_span)
    expected_end = expected_start + len(expected_span)

    assert detection.segment_id == segment_id
    assert detection.start_idx == expected_start
    assert detection.end_idx == expected_end
    assert str(detection.entity_type) == "ADDRESS"
    assert detection.confidence is None
    assert detection.source == "AddressRecognizer"

    assert detection.model_dump(mode="json")["tier"] == DetectionTier.RULE_ANCHORED.value

    assert detection.original_value == expected_span
    assert detection.normalized == expected_span

    ProxyContext(
        raw_prompt=raw,
        detected_entities=[detection],
    ).validate_detected_spans()


@pytest.mark.skipif(
    not ADDRESS_SUPPORTED_AT_COLLECTION,
    reason="R7_S3_PREIMPLEMENTATION_ADDRESS_UNSUPPORTED",
)
@pytest.mark.parametrize(
    "case",
    NEGATIVE_CASES,
    ids=lambda case: str(case["id"]),
)
def test_address_negative_runtime_contract(
    service: L3AnalyzerService,
    case: dict[str, Any],
) -> None:
    raw = str(case["text"])
    segment_id = f"r7-s3-{case['id']}"

    detections = service.analyze(
        raw,
        segment_id,
        entities=["ADDRESS"],
    )

    assert detections == []
