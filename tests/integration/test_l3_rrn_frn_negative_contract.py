"""Actual L3 RRN/FRN negative input contract using existing synthetic fixtures.

Each negative case checks the registered Producer and the explicit-entity
L3 service. Case IDs contain no identifier surface. Positive controls preserve
the previously established True -> DETERMINISTIC path.
"""

import pytest

from privacy_proxy.l3.registry import validate_registry
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectionTier
from tests.fixtures import FRN_VALID, RRN_VALID

CORE_DTO_FIELDS = {
    "segment_id",
    "start_idx",
    "end_idx",
    "entity_type",
    "confidence",
    "source",
    "tier",
    "original_value",
    "normalized",
}

ENTITY_CASES = (
    pytest.param("KR_RRN", RRN_VALID, id="RRN"),
    pytest.param("KR_FRN", FRN_VALID, id="FRN"),
)

NEGATIVE_CASES = (
    pytest.param(
        "N01_INVALID_MONTH",
        "month_zero",
        "month pattern excludes zero",
        id="N01-month-zero",
    ),
    pytest.param(
        "N02_INVALID_DAY",
        "day_zero",
        "day pattern excludes zero",
        id="N02-day-zero",
    ),
    pytest.param(
        "N03_INVALID_CATEGORY",
        "category_zero",
        "RRN and FRN category patterns exclude zero",
        id="N03-category-zero",
    ),
    pytest.param(
        "N04_SHORT_SURFACE",
        "short",
        "pattern length and validator length reject a shortened surface",
        id="N04-short",
    ),
    pytest.param(
        "N05_INTERNAL_NON_DIGIT",
        "internal_non_digit",
        "pattern digit run and validator reject a non-digit",
        id="N05-internal-non-digit",
    ),
    pytest.param(
        "N06_LEADING_DIGIT",
        "leading_digit",
        "pattern left digit boundary excludes an adjacent digit",
        id="N06-leading-digit",
    ),
    pytest.param(
        "N07_TRAILING_DIGIT",
        "trailing_digit",
        "pattern right digit boundary excludes an adjacent digit",
        id="N07-trailing-digit",
    ),
)


@pytest.fixture(scope="module")
def service() -> L3AnalyzerService:
    return L3AnalyzerService()


def _producer(service: L3AnalyzerService, entity: str):
    return validate_registry(service._analyzer.registry)[entity]


def _negative_surface(base: str, mutation: str) -> str:
    if mutation == "month_zero":
        return base[:2] + "00" + base[4:]
    if mutation == "day_zero":
        return base[:4] + "00" + base[6:]
    if mutation == "category_zero":
        return base[:7] + "0" + base[8:]
    if mutation == "short":
        return base[:-1]
    if mutation == "internal_non_digit":
        return base[:9] + "X" + base[10:]
    if mutation == "leading_digit":
        return "9" + base
    if mutation == "trailing_digit":
        return base + "9"
    raise AssertionError("UNKNOWN_MUTATION")


def _fail(case_id: str, reason: str) -> None:
    pytest.fail(f"{case_id}:{reason}", pytrace=False)


@pytest.mark.parametrize(("entity", "base"), ENTITY_CASES)
@pytest.mark.parametrize(("case_id", "mutation", "purpose"), NEGATIVE_CASES)
def test_negative_surface_rejected_by_registered_producer_and_service(
    service: L3AnalyzerService,
    entity: str,
    base: str,
    case_id: str,
    mutation: str,
    purpose: str,
) -> None:
    """The case ID, target entity, purpose and rejection basis are parametrized."""
    assert purpose
    raw = _negative_surface(base, mutation)
    producer = _producer(service, entity)

    if mutation in {"short", "internal_non_digit"} and producer.validate_result(raw) is not False:
        _fail(case_id, "VALIDATOR_FALSE_EXPECTED")

    if producer.analyze(raw, [entity]):
        _fail(case_id, "PRODUCER_UNEXPECTED_CANDIDATE")
    if service.analyze(raw, "b4-negative", entities=[entity]):
        _fail(case_id, "SERVICE_UNEXPECTED_DETECTION")


@pytest.mark.parametrize(("entity", "base"), ENTITY_CASES)
def test_valid_synthetic_control_preserves_registered_producer_and_dto(
    service: L3AnalyzerService, entity: str, base: str
) -> None:
    """A real valid Producer candidate still reaches the canonical L3 DTO."""
    producer = _producer(service, entity)
    if producer.validate_result(base) is not True:
        _fail(entity, "VALID_CONTROL_VALIDATOR_NOT_TRUE")

    results = producer.analyze(base, [entity])
    if len(results) != 1:
        _fail(entity, "VALID_CONTROL_PRODUCER_COUNT")
    if (results[0].entity_type, results[0].start, results[0].end) != (
        entity,
        0,
        len(base),
    ):
        _fail(entity, "VALID_CONTROL_PRODUCER_SPAN")

    detections = service.analyze(base, "b4-positive-control", entities=[entity])
    if len(detections) != 1:
        _fail(entity, "VALID_CONTROL_SERVICE_COUNT")
    detection = detections[0]
    fields = detection.model_dump()
    if not CORE_DTO_FIELDS.issubset(fields):
        _fail(entity, "VALID_CONTROL_DTO_FIELDS")
    if (
        detection.entity_type != entity
        or detection.segment_id != "b4-positive-control"
        or detection.start_idx != 0
        or detection.end_idx != len(base)
        or base[detection.start_idx : detection.end_idx] != detection.original_value
        or detection.normalized != detection.original_value
        or detection.confidence is not None
        or detection.source != producer.name
        or detection.tier is not DetectionTier.DETERMINISTIC
    ):
        _fail(entity, "VALID_CONTROL_DTO_CONTRACT")
