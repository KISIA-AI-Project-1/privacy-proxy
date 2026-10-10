"""R6-S6 PERSON_EN default-request contract.

This file is intentionally introduced before implementation.
R6-S6-B2 adjudicated PERSON_EN as INCLUDE_BY_DEFAULT.

Expected pre-implementation state:
- 2 RED policy tests
- 4 GREEN compatibility controls
"""

from privacy_proxy.l3.registry import DEFAULT_ENTITIES, SUPPORTED_ENTITIES
from privacy_proxy.l3.service import L3AnalyzerService

PRE_R6_S6_DEFAULT_ENTITIES = (
    "KR_RRN",
    "KR_FRN",
    "KR_PASSPORT",
    "KR_DRIVER_LICENSE",
    "KR_BRN",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "AGE",
    "AGE_GROUP",
    "DATE_OF_BIRTH",
    "LOCATION",
)


def _entity_name(item) -> str:
    return str(
        getattr(
            item.entity_type,
            "value",
            item.entity_type,
        )
    )


def _tier_name(item) -> str:
    return str(
        getattr(
            item.tier,
            "value",
            item.tier,
        )
    )


def _person_en(results):
    return [item for item in results if _entity_name(item) == "PERSON_EN"]


def test_person_en_is_in_default_entities():
    assert "PERSON_EN" in DEFAULT_ENTITIES


def test_none_request_detects_person_en():
    service = L3AnalyzerService()

    results = service.analyze(
        "John Smith contacted support.",
        "r6-s6-c1-none",
        entities=None,
    )

    persons = _person_en(results)

    assert len(persons) == 1

    detection = persons[0]

    assert detection.original_value == "John Smith"
    assert detection.source == "PersonEnRecognizer"
    assert detection.confidence is None
    assert _tier_name(detection) == "model"


def test_pre_r6_s6_default_entities_are_preserved():
    assert set(PRE_R6_S6_DEFAULT_ENTITIES).issubset(set(DEFAULT_ENTITIES))


def test_empty_explicit_set_remains_empty():
    service = L3AnalyzerService()

    results = service.analyze(
        "John Smith contacted support.",
        "r6-s6-c1-empty",
        entities=[],
    )

    assert results == []


def test_explicit_person_en_request_remains_supported():
    service = L3AnalyzerService()

    results = service.analyze(
        "John Smith contacted support.",
        "r6-s6-c1-explicit",
        entities=["PERSON_EN"],
    )

    persons = _person_en(results)

    assert len(persons) == 1

    detection = persons[0]

    assert detection.original_value == "John Smith"
    assert detection.source == "PersonEnRecognizer"
    assert detection.confidence is None
    assert _tier_name(detection) == "model"


def test_person_ko_remains_outside_l3():
    assert "PERSON_KO" not in SUPPORTED_ENTITIES
    assert "PERSON_KO" not in DEFAULT_ENTITIES
