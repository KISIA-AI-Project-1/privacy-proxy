"""R5-S4-B service/registry/adapter tests with a controlled model dependency.

No real ko_core_news_lg execution or F01-F03 frozen regression is claimed.
Only the model loader/inference is mocked; canonical conversion is real.
"""

from unittest.mock import patch

import pytest
from presidio_analyzer import RecognizerResult
from presidio_analyzer.nlp_engine import NoOpNlpEngine
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    KrBrnRecognizer,
    KrDriverLicenseRecognizer,
    KrFrnRecognizer,
    KrPassportRecognizer,
    KrRrnRecognizer,
    PhoneRecognizer,
)

from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3.age_group_recognizer import AgeGroupStatementRecognizer
from privacy_proxy.l3.age_recognizer import AgeStatementRecognizer
from privacy_proxy.l3.date_of_birth_recognizer import DateOfBirthRecognizer
from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.provenance import ProvenanceError, resolve_producer
from privacy_proxy.l3.registry import PRODUCER_TYPES, RegistryConfigurationError, validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError, UnsupportedCapabilityError
from privacy_proxy.l3.tier_mapping import tier_for
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext
from tests.fixtures import PASSPORT
from tests.unit.test_location import (
    ENTITY,
    FIELDS,
    PRIVATE,
    REJECTIONS,
    candidate,
    controlled_model,
    location_class,
)

SEGMENT = "location-segment-42"
EXISTING_TYPES = {
    "KR_RRN": KrRrnRecognizer,
    "KR_FRN": KrFrnRecognizer,
    "KR_PASSPORT": KrPassportRecognizer,
    "KR_DRIVER_LICENSE": KrDriverLicenseRecognizer,
    "KR_BRN": KrBrnRecognizer,
    "PHONE_NUMBER": PhoneRecognizer,
    "EMAIL_ADDRESS": EmailRecognizer,
    "AGE": AgeStatementRecognizer,
    "AGE_GROUP": AgeGroupStatementRecognizer,
    "DATE_OF_BIRTH": DateOfBirthRecognizer,
}


def check_detection(detection, raw, surface, producer, segment=SEGMENT):
    assert type(detection) is DetectedPII
    assert tuple(detection.model_dump()) == FIELDS
    assert detection.model_fields_set == set(FIELDS)
    assert detection.entity_type == ENTITY
    assert detection.segment_id == segment
    assert detection.confidence is None
    assert detection.tier is DetectionTier.MODEL
    assert detection.source == producer.name
    assert 0 <= detection.start_idx < detection.end_idx <= len(raw)
    assert raw[detection.start_idx : detection.end_idx] == detection.original_value == surface
    assert detection.normalized == detection.original_value
    assert detection.model_dump(mode="json")["tier"] == DetectionTier.MODEL.value
    ProxyContext(raw_prompt=raw, detected_entities=[detection]).validate_detected_spans()
    L3Output(raw, (detection,))


def test_p01_p02_g01_exact_eleven_producers(monkeypatch):
    controlled_model(monkeypatch, "")
    service = L3AnalyzerService()
    registry = service._analyzer.registry
    producers = validate_registry(registry)
    assert len(registry.recognizers) == 11
    assert set(producers) == set(EXISTING_TYPES) | {ENTITY}
    assert len({producer.id for producer in registry.recognizers}) == 11
    assert registry.supported_languages == ["ko"]
    assert sum(ENTITY in producer.supported_entities for producer in registry.recognizers) == 1
    for entity, cls in EXISTING_TYPES.items():
        assert type(producers[entity]) is cls
        assert producers[entity].supported_language == "ko"
        assert producers[entity].supported_entities == [entity]


def test_p03_p04_exact_location_registration(monkeypatch):
    controlled_model(monkeypatch, "")
    service = L3AnalyzerService()
    producers = validate_registry(service._analyzer.registry)
    assert ENTITY in producers
    cls = location_class()
    assert PRODUCER_TYPES[ENTITY] is cls
    assert type(producers[ENTITY]) is cls
    assert producers[ENTITY].supported_language == "ko"
    assert producers[ENTITY].supported_entities == [ENTITY]


@pytest.mark.parametrize("mutation", ["subclass", "duplicate", "language", "entities"])
def test_p03_p04_registry_rejects_unverified_location(monkeypatch, mutation):
    controlled_model(monkeypatch, "")
    service = L3AnalyzerService()
    registry = service._analyzer.registry
    producers = validate_registry(registry)
    assert ENTITY in producers
    producer = producers[ENTITY]
    if mutation == "subclass":

        class UnverifiedLocation(location_class()):
            pass

        unverified = UnverifiedLocation()
        with pytest.raises(ProvenanceError):
            tier_for(unverified, ENTITY, "경기도")
        registry.recognizers[registry.recognizers.index(producer)] = unverified
    elif mutation == "duplicate":
        registry.recognizers.append(producer)
    elif mutation == "language":
        producer.supported_language = "en"
    else:
        producer.supported_entities = [ENTITY, "LOCATION_INFORMAL"]
    with pytest.raises(RegistryConfigurationError):
        service.analyze("", SEGMENT, entities=[ENTITY])


@pytest.mark.parametrize("suffix", ["", "에", "이고", "입니다"])
@pytest.mark.parametrize("segment", [SEGMENT, "location-segment-99"])
def test_r01_i04_canonical_service_span(monkeypatch, suffix, segment):
    raw = "😀 표본: 경기도" + suffix + "!"
    model, _ = controlled_model(monkeypatch, raw, [candidate(raw, "경기도" + suffix)])
    service = L3AnalyzerService()
    detections = service.analyze(raw, segment, entities=[ENTITY])
    assert len(detections) == 1
    producer = validate_registry(service._analyzer.registry)[ENTITY]
    check_detection(detections[0], raw, "경기도", producer, segment)
    assert detections[0].start_idx == raw.index("경기도")
    assert model.called


def test_r02_i05_decomposition_precedes_common_adapter(monkeypatch):
    raw = "😀 표본: 경기도 수원시 영통구에."
    controlled_model(monkeypatch, raw, [candidate(raw, "경기도 수원시 영통구에")])
    service = L3AnalyzerService()
    with patch("privacy_proxy.l3.service.adapt_result", wraps=adapt_result) as adapter:
        detections = service.analyze(raw, SEGMENT, entities=[ENTITY])
    producer = validate_registry(service._analyzer.registry)[ENTITY]
    expected = ["경기도", "수원시", "영통구"]
    assert len(detections) == adapter.call_count == 3
    inputs = sorted((call.args[0] for call in adapter.call_args_list), key=lambda r: r.start)
    assert all(isinstance(result, RecognizerResult) for result in inputs)
    assert [raw[result.start : result.end] for result in inputs] == expected
    for result, detection, surface in zip(
        inputs, sorted(detections, key=lambda d: d.start_idx), expected, strict=True
    ):
        direct = adapt_result(result, raw, SEGMENT, service._analyzer.registry)
        assert type(direct) is DetectedPII
        assert direct.model_dump() == detection.model_dump()
        assert resolve_producer(result, service._analyzer.registry) is producer
        check_detection(detection, raw, surface, producer)
    L3Output(raw, tuple(detections))


@pytest.mark.parametrize("surface", REJECTIONS)
def test_r03_r04_service_graceful_zero(monkeypatch, surface):
    raw = "표본: " + surface
    model, _ = controlled_model(monkeypatch, raw, [candidate(raw, surface)])
    service = L3AnalyzerService()
    assert service.analyze(raw, SEGMENT, entities=[ENTITY]) == []
    assert model.called


@pytest.mark.parametrize("label", ["PS", "OG", "GPE", "LOC"])
def test_m01_service_lc_only(monkeypatch, label):
    raw = "경기도"
    model, _ = controlled_model(monkeypatch, raw, [candidate(raw, raw, label)])
    service = L3AnalyzerService()
    assert service.analyze(raw, SEGMENT, entities=[ENTITY]) == []
    assert model.called


@pytest.mark.parametrize(
    "requested", [[ENTITY], ["EMAIL_ADDRESS"], [ENTITY, "EMAIL_ADDRESS", "KR_PASSPORT"], [], None]
)
def test_i01_i02_i03_requested_isolation_and_mixed_entities(monkeypatch, requested):
    raw = "표본: 경기도에. audit@example.com " + PASSPORT
    controlled_model(monkeypatch, raw, [candidate(raw, "경기도에")])
    service = L3AnalyzerService()
    detections = service.analyze(raw, SEGMENT, entities=requested)
    wanted = {ENTITY, "EMAIL_ADDRESS", "KR_PASSPORT"} if requested is None else set(requested)
    assert {d.entity_type for d in detections} == wanted
    assert len(detections) == len(wanted)
    for detection in detections:
        assert 0 <= detection.start_idx < detection.end_idx <= len(raw)
        assert raw[detection.start_idx : detection.end_idx] == detection.original_value
        assert detection.normalized == detection.original_value
        assert detection.segment_id == SEGMENT
        assert detection.confidence is None
        if detection.entity_type == ENTITY:
            producer = validate_registry(service._analyzer.registry)[ENTITY]
            check_detection(detection, raw, "경기도", producer)
        else:
            assert detection.tier is DetectionTier.RULE_ANCHORED
    L3Output(raw, tuple(detections))


@pytest.mark.parametrize(
    "key", [RecognizerResult.RECOGNIZER_NAME_KEY, RecognizerResult.RECOGNIZER_IDENTIFIER_KEY]
)
def test_p06_provenance_conflict_rejected_direct_and_service(monkeypatch, key, caplog):
    raw = "경기도"
    controlled_model(monkeypatch, raw, [candidate(raw, raw)])
    service = L3AnalyzerService()
    registry = service._analyzer.registry
    producers = validate_registry(registry)
    assert ENTITY in producers
    results = producers[ENTITY].analyze(raw, [ENTITY])
    assert len(results) == 1
    results[0].recognition_metadata[key] = PRIVATE
    with pytest.raises(ProvenanceError) as direct:
        adapt_result(results[0], raw, SEGMENT, registry)
    with (
        patch.object(service._analyzer, "analyze", return_value=results),
        pytest.raises(L3RuntimeError) as wrapped,
    ):
        service.analyze(raw, SEGMENT, entities=[ENTITY])
    for secret in (PRIVATE, raw):
        assert secret not in str(direct.value)
        assert secret not in str(wrapped.value)
        assert secret not in caplog.text


@pytest.mark.parametrize("failure", ["missing", "load", "inference", "lc_missing"])
def test_d01_d04_dependency_failure_is_public_runtime_error(monkeypatch, failure, caplog):
    raw = "표본: 경기도"
    model, loader = controlled_model(
        monkeypatch, raw, labels=("PS",) if failure == "lc_missing" else ("LC",)
    )
    if failure == "missing":
        loader.side_effect = OSError(PRIVATE)
    elif failure == "load":
        loader.side_effect = RuntimeError(PRIVATE)
    elif failure == "inference":
        model.side_effect = RuntimeError(PRIVATE)
    # Accept eager or lazy loading, but never unsupported capability or [].
    with pytest.raises(L3RuntimeError) as caught:
        service = L3AnalyzerService()
        service.analyze(raw, SEGMENT, entities=[ENTITY])
    assert loader.called
    if failure == "inference":
        assert model.called
    for secret in (PRIVATE, raw):
        assert secret not in str(caught.value)
        assert secret not in caplog.text


@pytest.mark.parametrize("surface", ["강남 쪽", "역삼 근처", "저희 동네"])
def test_b01_informal_expression_not_owned(monkeypatch, surface):
    controlled_model(monkeypatch, surface, [candidate(surface, surface)])
    service = L3AnalyzerService()
    assert service.analyze(surface, SEGMENT, entities=[ENTITY]) == []


@pytest.mark.parametrize(
    "entity", ["LOCATION_INFORMAL", "ADDRESS", "ADDRESS_ROAD", "ADDRESS_LOT", "ADDRESS_DETAIL"]
)
def test_b01_b02_capabilities_remain_unsupported(monkeypatch, entity):
    controlled_model(monkeypatch, "")
    service = L3AnalyzerService()
    with pytest.raises(UnsupportedCapabilityError, match="UNSUPPORTED_ENTITY"):
        service.analyze("", SEGMENT, entities=[entity])


def test_b02_address_text_does_not_expand_location_span(monkeypatch):
    raw = "표본 주소: 경기도 수원시 영통구 예시로 999 가상동 999호"
    controlled_model(monkeypatch, raw, [candidate(raw, "경기도 수원시 영통구")])
    service = L3AnalyzerService()
    detections = service.analyze(raw, SEGMENT, entities=[ENTITY])
    producer = validate_registry(service._analyzer.registry)[ENTITY]
    expected = ["경기도", "수원시", "영통구"]
    assert len(detections) == 3
    for detection, surface in zip(
        sorted(detections, key=lambda d: d.start_idx), expected, strict=True
    ):
        check_detection(detection, raw, surface, producer)


def test_g03_global_noop_boundary_preserved(monkeypatch):
    controlled_model(monkeypatch, "")
    analyzer = L3AnalyzerService()._analyzer
    assert type(analyzer.nlp_engine) is NoOpNlpEngine
    assert analyzer.supported_languages == ["ko"]
    assert analyzer.nlp_engine.get_supported_languages() == ["ko"]
    assert analyzer.nlp_engine.get_supported_entities() == []
    assert analyzer.log_decision_process is False
