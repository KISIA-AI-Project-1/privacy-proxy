"""R5-S4-B controlled LOCATION tests; no real model or frozen-oracle claim.

The dependency seam is spaCy's load_model, used by spacy.load (including
imported aliases). Constructor versus lazy loading remains an implementation
choice. Import the planned producer only inside tests, outside raises blocks,
so its absence is a RED failure and cannot masquerade as dependency handling.
"""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from presidio_analyzer import RecognizerResult
from pydantic import ValidationError

from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.provenance import ProvenanceError
from privacy_proxy.l3.registry import build_registry, validate_registry
from privacy_proxy.l3.tier_mapping import tier_for
from privacy_proxy.schemas import DetectedPII, DetectionTier

ENTITY = "LOCATION"
PRIVATE = "SYNTHETIC_LOCATION_DEPENDENCY_ERROR"
CORE_FIELDS = (
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

ANCHOR_FIELDS = (
    "anchor_text",
    "anchor_start",
    "anchor_end",
)

FIELDS = CORE_FIELDS + ANCHOR_FIELDS
REJECTIONS = [
    pytest.param("경기도수원시영통구", id="R03-three-level"),
    pytest.param("수원시영통구", id="R03-two-level"),
    pytest.param("부산광역시해운대구", id="R03-metropolitan"),
    pytest.param("영통구에서", id="R04-unsupported-suffix"),
    pytest.param("강남구였으며", id="R04-unsupported-ending"),
]


def location_class():
    return import_module("privacy_proxy.l3.location_recognizer").LocationRecognizer


def controlled_model(monkeypatch, raw, candidates=(), *, failure=None, labels=("LC",)):
    """Return a model/loader mock; candidate tuples are explicit raw spans.

    This fixture performs no detection, suffix trimming or decomposition.
    The production producer must perform all refinement.
    """
    spans = [
        SimpleNamespace(
            start_char=start,
            end_char=end,
            text=raw[start:end],
            label_=label,
        )
        for start, end, label in candidates
    ]
    for start, end, _ in candidates:
        assert 0 <= start < end <= len(raw)
    ner = SimpleNamespace(labels=labels)
    model = Mock(
        return_value=SimpleNamespace(text=raw, ents=tuple(spans)),
        side_effect=failure,
    )
    model.lang = "ko"
    model.meta = {"lang": "ko", "name": "core_news_lg", "version": "3.8.0"}
    model.pipe_names = ["ner"]
    model.pipe_labels = {"ner": list(labels)}
    model.has_pipe.side_effect = lambda name: name == "ner"
    model.get_pipe.side_effect = lambda name: ner if name == "ner" else None
    loader = Mock(return_value=model)
    monkeypatch.setattr("spacy.util.load_model", loader)
    return model, loader


def candidate(raw, surface, label="LC"):
    start = raw.index(surface)
    return (start, start + len(surface), label)


def assert_results(results, raw, expected):
    ordered = sorted(results, key=lambda result: result.start)
    assert len(ordered) == len(expected)
    assert [(r.start, r.end, raw[r.start : r.end]) for r in ordered] == expected
    for result in ordered:
        assert isinstance(result, RecognizerResult)
        assert result.entity_type == ENTITY
        assert 0 <= result.start < result.end <= len(raw)


def test_s01_s02_canonical_location_schema():
    detection = DetectedPII(
        segment_id="location-schema",
        start_idx=2,
        end_idx=5,
        entity_type=ENTITY,
        confidence=None,
        source="SyntheticLocationSchemaFixture",
        tier=DetectionTier.MODEL,
        original_value="경기도",
        normalized="경기도",
    )
    assert tuple(DetectedPII.model_fields) == FIELDS
    assert tuple(detection.model_dump()) == FIELDS
    assert detection.confidence is None
    assert detection.tier is DetectionTier.MODEL
    assert "😀 경기도"[detection.start_idx : detection.end_idx] == detection.original_value
    assert detection.normalized == detection.original_value


@pytest.mark.parametrize(
    "extra", ["admin_type", "detail_level", "normalization_rule", "removed_suffix"]
)
def test_s05_b03_historical_metadata_is_not_canonical(extra):
    with pytest.raises(ValidationError) as caught:
        DetectedPII(
            segment_id="location-schema",
            start_idx=0,
            end_idx=3,
            entity_type=ENTITY,
            confidence=None,
            source="SyntheticLocationSchemaFixture",
            tier=DetectionTier.MODEL,
            original_value="경기도",
            normalized="경기도",
            **{extra: PRIVATE},
        )
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("suffix", ["에", "이고", "입니다"])
def test_r01_controlled_terminal_suffix(monkeypatch, suffix):
    raw = "😀 표본: 경기도" + suffix + "!"
    surface = "경기도" + suffix
    model, loader = controlled_model(monkeypatch, raw, [candidate(raw, surface)])
    producer = location_class()()
    results = producer.analyze(raw, [ENTITY])
    start = raw.index("경기도")
    assert_results(results, raw, [(start, start + 3, "경기도")])
    assert model.called
    assert loader.call_args.args[0] == "ko_core_news_lg"


def test_r02_one_candidate_emits_three_results_before_adapter(monkeypatch):
    raw = "😀 표본: 경기도 수원시 영통구에."
    controlled_model(monkeypatch, raw, [candidate(raw, "경기도 수원시 영통구에")])
    results = location_class()().analyze(raw, [ENTITY])
    expected = [(raw.index(s), raw.index(s) + len(s), s) for s in ("경기도", "수원시", "영통구")]
    assert_results(results, raw, expected)


@pytest.mark.parametrize("surface", ["수원시 영통구", "영통구"])
def test_r02_no_missing_parent_inference(monkeypatch, surface):
    raw = "표본: " + surface
    controlled_model(monkeypatch, raw, [candidate(raw, surface)])
    expected = [(raw.index(s), raw.index(s) + len(s), s) for s in surface.split()]
    assert_results(location_class()().analyze(raw, [ENTITY]), raw, expected)


@pytest.mark.parametrize("surface", REJECTIONS)
def test_r03_r04_graceful_zero_emission(monkeypatch, surface):
    raw = "표본: " + surface
    model, _ = controlled_model(monkeypatch, raw, [candidate(raw, surface)])
    assert location_class()().analyze(raw, [ENTITY]) == []
    assert model.called


@pytest.mark.parametrize("label", ["PS", "OG", "GPE", "LOC"])
def test_m01_only_lc_is_location_evidence(monkeypatch, label):
    raw = "표본: 경기도"
    model, _ = controlled_model(monkeypatch, raw, [candidate(raw, "경기도", label)])
    assert location_class()().analyze(raw, [ENTITY]) == []
    assert model.called


@pytest.mark.parametrize("partial", [False, True])
def test_m02_model_miss_is_not_recovered(monkeypatch, partial):
    raw = "표본: 경기도 수원시 영통구"
    candidates = [candidate(raw, "영통구")] if partial else []
    model, _ = controlled_model(monkeypatch, raw, candidates)
    expected = [(raw.index("영통구"), len(raw), "영통구")] if partial else []
    assert_results(location_class()().analyze(raw, [ENTITY]), raw, expected)
    assert model.called


@pytest.mark.parametrize("entities", [[], ["EMAIL_ADDRESS"], ["LOCATION_INFORMAL"], ["ADDRESS"]])
def test_requested_entity_isolation(monkeypatch, entities):
    raw = "경기도"
    controlled_model(monkeypatch, raw, [candidate(raw, raw)])
    assert location_class()().analyze(raw, entities) == []


@pytest.mark.parametrize("surface", ["강남 쪽", "역삼 근처", "저희 동네"])
def test_b01_informal_lc_candidate_does_not_expand_ownership(monkeypatch, surface):
    controlled_model(monkeypatch, surface, [candidate(surface, surface)])
    assert location_class()().analyze(surface, [ENTITY]) == []


def test_p04_p05_producer_capability_and_metadata(monkeypatch):
    raw = "경기도 수원시 영통구에"
    controlled_model(monkeypatch, raw, [candidate(raw, raw)])
    producer = location_class()()
    assert producer.supported_language == "ko"
    assert producer.supported_entities == [ENTITY]
    results = producer.analyze(raw, [ENTITY])
    assert len(results) == 3
    for result in results:
        assert result.entity_type == ENTITY
        assert result.recognition_metadata[RecognizerResult.RECOGNIZER_NAME_KEY] == producer.name
        assert (
            result.recognition_metadata[RecognizerResult.RECOGNIZER_IDENTIFIER_KEY] == producer.id
        )


@pytest.mark.parametrize("score", [0.01, 0.5, 1.0])
def test_t01_t03_m03_numeric_score_is_not_canonical_evidence(monkeypatch, score):
    raw = "경기도에"
    controlled_model(monkeypatch, raw, [candidate(raw, raw)])
    registry = build_registry()
    producers = validate_registry(registry)
    assert ENTITY in producers
    producer = producers[ENTITY]
    results = producer.analyze(raw, [ENTITY])
    assert len(results) == 1
    results[0].score = score
    detection = adapt_result(results[0], raw, "location-score", registry)
    assert detection.confidence is None
    assert detection.tier is DetectionTier.MODEL
    assert detection.original_value == detection.normalized == "경기도"
    assert raw[detection.start_idx : detection.end_idx] == detection.original_value


def test_t02_entity_label_alone_is_not_tier_evidence():
    with pytest.raises(ProvenanceError, match="UNVERIFIED_TIER_PRODUCER"):
        tier_for(object(), ENTITY, "경기도")


@pytest.mark.parametrize("failure", [OSError, RuntimeError])
def test_d01_d02_model_missing_or_load_failure_is_explicit(monkeypatch, failure):
    raw = "경기도"
    _, loader = controlled_model(monkeypatch, raw)
    cls = location_class()  # Missing planned module must not satisfy raises.
    loader.side_effect = failure(PRIVATE)
    with pytest.raises((OSError, RuntimeError, ValueError)):
        cls().analyze(raw, [ENTITY])
    assert loader.called


def test_d03_inference_failure_is_not_empty(monkeypatch):
    raw = "경기도"
    model, _ = controlled_model(monkeypatch, raw, failure=RuntimeError(PRIVATE))
    cls = location_class()
    with pytest.raises((RuntimeError, ValueError)):
        cls().analyze(raw, [ENTITY])
    assert model.called


def test_d04_required_lc_capability_missing_is_failure(monkeypatch):
    raw = "경기도"
    _, loader = controlled_model(monkeypatch, raw, labels=("PS", "OG"))
    cls = location_class()
    with pytest.raises((RuntimeError, ValueError)):
        cls().analyze(raw, [ENTITY])
    assert loader.called
