"""R4-1F DATE_OF_BIRTH service integration tests.

Synthetic fixtures only. These tests verify the canonical L3 service boundary,
not recognizer-local parsing behavior already covered by the unit suite.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3.date_of_birth_recognizer import DateOfBirthRecognizer
from privacy_proxy.l3.registry import validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, UnsupportedCapabilityError
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext

ENTITY = "DATE_OF_BIRTH"
SEGMENT = "dob-segment-1"

FIELDS = (
    "segment_id",
    "start_idx",
    "end_idx",
    "entity_type",
    "confidence",
    "source",
    "tier",
    "original_value",
    "normalized",
)


@pytest.fixture
def service() -> L3AnalyzerService:
    return L3AnalyzerService()


@pytest.fixture
def location_dependency_available(monkeypatch):
    """Controlled LOCATION dependency for default-all service tests."""
    ner = SimpleNamespace(labels=("LC",))
    model = Mock(
        side_effect=lambda text: SimpleNamespace(text=text, ents=()),
    )
    model.lang = "ko"
    model.meta = {
        "lang": "ko",
        "name": "core_news_lg",
        "version": "3.8.0",
    }
    model.pipe_names = ["ner"]
    model.pipe_labels = {"ner": ["LC"]}
    model.has_pipe.side_effect = lambda name: name == "ner"
    model.get_pipe.side_effect = lambda name: ner if name == "ner" else None

    from spacy import util as spacy_util

    original_load_model = spacy_util.load_model

    def routed_load_model(name, *args, **kwargs):
        if name == "ko_core_news_lg":
            return model
        return original_load_model(name, *args, **kwargs)

    loader = Mock(side_effect=routed_load_model)
    monkeypatch.setattr(spacy_util, "load_model", loader)

    return loader


def _check_detection(
    detection: DetectedPII,
    raw: str,
    surface: str,
    segment: str = SEGMENT,
) -> None:
    assert type(detection) is DetectedPII

    payload = detection.model_dump()

    assert tuple(payload) == FIELDS
    assert set(payload) == set(DetectedPII.model_fields)
    assert len(payload) == 9

    assert detection.segment_id == segment
    assert detection.entity_type == ENTITY
    assert detection.confidence is None
    assert detection.source == "DateOfBirthRecognizer"
    assert detection.tier is DetectionTier.RULE_ANCHORED

    assert 0 <= detection.start_idx < detection.end_idx <= len(raw)
    assert raw[detection.start_idx : detection.end_idx] == surface
    assert detection.original_value == surface
    assert detection.normalized == detection.original_value

    wire = detection.model_dump(mode="json")

    assert wire["tier"] == "rule_anchored"
    assert wire["confidence"] is None

    ProxyContext(
        raw_prompt=raw,
        detected_entities=[detection],
    ).validate_detected_spans()

    L3Output(
        raw,
        (detection,),
    )


def test_real_service_emits_canonical_dob(
    service: L3AnalyzerService,
) -> None:
    raw = "생년월일은 2004-01-02입니다."

    detections = service.analyze(
        raw,
        SEGMENT,
        entities=[ENTITY],
    )

    assert len(detections) == 1

    _check_detection(
        detections[0],
        raw,
        "2004-01-02",
    )


@pytest.mark.parametrize(
    ("raw", "surface"),
    [
        ("생년월일 20040102", "20040102"),
        ("생년월일 2004년 1월 2일", "2004년 1월 2일"),
        ("2004년 1월 2일생입니다.", "2004년 1월 2일"),
    ],
)
def test_supported_surfaces_reach_canonical_service_output(
    service: L3AnalyzerService,
    raw: str,
    surface: str,
) -> None:
    detections = service.analyze(
        raw,
        SEGMENT,
        entities=[ENTITY],
    )

    assert len(detections) == 1

    _check_detection(
        detections[0],
        raw,
        surface,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "2004-01-02",
        "주문일은 2004-01-02입니다.",
        "생년월일 2004-02-30",
    ],
)
def test_semantic_rejections_remain_empty_at_service_boundary(
    service: L3AnalyzerService,
    raw: str,
) -> None:
    assert (
        service.analyze(
            raw,
            SEGMENT,
            entities=[ENTITY],
        )
        == []
    )


def test_registry_exposes_verified_dob_producer(
    service: L3AnalyzerService,
) -> None:
    producers = validate_registry(
        service._analyzer.registry,
    )

    assert ENTITY in producers

    producer = producers[ENTITY]

    assert type(producer) is DateOfBirthRecognizer
    assert producer.name == "DateOfBirthRecognizer"
    assert producer.supported_entities == [ENTITY]
    assert producer.supported_language == "ko"


def test_default_capability_includes_dob(
    service: L3AnalyzerService,
    location_dependency_available,
) -> None:
    raw = "생년월일은 2004-01-02입니다."

    detections = service.analyze(
        raw,
        SEGMENT,
    )

    dob = [detection for detection in detections if detection.entity_type == ENTITY]

    assert len(dob) == 1

    _check_detection(
        dob[0],
        raw,
        "2004-01-02",
    )


def test_dob_and_age_coexist(
    service: L3AnalyzerService,
) -> None:
    raw = "생년월일은 2004-01-02입니다. 나이: 22세"

    detections = service.analyze(
        raw,
        SEGMENT,
        entities=[ENTITY, "AGE"],
    )

    assert {detection.entity_type for detection in detections} == {
        ENTITY,
        "AGE",
    }

    for detection in detections:
        assert raw[detection.start_idx : detection.end_idx] == detection.original_value
        assert detection.normalized == detection.original_value
        assert detection.confidence is None
        assert detection.tier is DetectionTier.RULE_ANCHORED


def test_other_unimplemented_capability_remains_unsupported(
    service: L3AnalyzerService,
) -> None:
    with pytest.raises(
        UnsupportedCapabilityError,
        match="UNSUPPORTED_ENTITY",
    ):
        service.analyze(
            "",
            SEGMENT,
            entities=["ADDRESS_ROAD"],
        )
