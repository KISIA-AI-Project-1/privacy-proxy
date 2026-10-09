"""H2 X-AJ / schema gates for the new AGE_GROUP capability cycle.

D7-E remains historical. DOB below is an explicit synthetic consumer fixture,
never evidence of an implemented L3 DOB producer. GENERALIZE passthrough and
equal plain/refined risk are known downstream limitations, not revised policy.
"""

from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

import pytest
from presidio_analyzer import RecognizerResult
from pydantic import ValidationError

from privacy_proxy.contracts.detection import DetectionValidationError
from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3 import age_group_recognizer as group_module
from privacy_proxy.l3.age_group_recognizer import AgeGroupStatementRecognizer
from privacy_proxy.l3.detection_adapter import adapt_result
from privacy_proxy.l3.provenance import ProvenanceError
from privacy_proxy.l3.registry import RegistryConfigurationError, validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError, UnsupportedCapabilityError
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError
from privacy_proxy.risk.quasi_identifiers import to_qi_feature
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext
from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore
from privacy_proxy.vault.tokenizer import Tokenizer
from tests.unit.test_age_group import CASES, REPEATED, REPEATED_START

RAW = "고객은 30대입니다."
REFINED = "고객은 30대 초반입니다."
SEGMENT = "h2-segment-42"
PRIVATE = "H2_PRIVATE_ERROR_SENTINEL"
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
ENTITIES = {
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
}
UNSUPPORTED = ("PERSON_EN", "ADDRESS")
ALIASES = ("AGEGROUP", "AGE-GROUP", "age_group", "ageGroup")
Z1 = "고객은 30대이며 실제 나이는 32세입니다."
Z2 = "나이: 32세, 연령대: 30대"
Z_EXPECTED = (
    (("AGE_GROUP", 4, 7, "30대"), ("AGE", 17, 20, "32세")),
    (("AGE", 4, 7, "32세"), ("AGE_GROUP", 14, 17, "30대")),
)


@pytest.fixture(scope="module")
def service():
    return L3AnalyzerService()


@pytest.fixture
def isolated():
    return L3AnalyzerService()


def check_payload(payload, raw, segment=SEGMENT):
    assert tuple(payload) == FIELDS == tuple(DetectedPII.model_fields)
    assert set(payload) == set(DetectedPII.model_fields)
    assert len(payload) == 9
    assert payload["segment_id"] == segment
    assert payload["entity_type"] == "AGE_GROUP"
    assert payload["confidence"] is None
    assert payload["source"] == "AgeGroupStatementRecognizer"
    assert payload["tier"] is DetectionTier.RULE_ANCHORED
    start, end = payload["start_idx"], payload["end_idx"]
    assert 0 <= start < end <= len(raw)
    assert raw[start:end] == payload["original_value"]
    assert payload["normalized"] == payload["original_value"]
    assert DetectedPII.model_validate(payload).model_dump() == payload


def check_detection(detection, raw, segment=SEGMENT):
    assert type(detection) is DetectedPII
    assert detection.model_fields_set == set(FIELDS)
    check_payload(detection.model_dump(), raw, segment)
    wire = detection.model_dump(mode="json")
    assert tuple(wire) == FIELDS
    assert wire["entity_type"] == "AGE_GROUP"
    assert wire["confidence"] is None
    assert wire["tier"] == "rule_anchored"


def producer(service, entity="AGE_GROUP"):
    return validate_registry(service._analyzer.registry)[entity]


def result(service, start=4, end=7):
    p = producer(service)
    return RecognizerResult(
        "AGE_GROUP",
        start,
        end,
        0.5,
        recognition_metadata={
            RecognizerResult.RECOGNIZER_NAME_KEY: p.name,
            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: p.id,
        },
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id + ":" + c.outcome)
def test_h2_real_runtime_semantics_and_schema(service, case):
    detections = service.analyze(case.raw, SEGMENT, entities=["AGE_GROUP"])
    actual = sorted((d.start_idx, d.end_idx, d.original_value) for d in detections)
    assert actual == list(case.expected)
    for detection in detections:
        check_detection(detection, case.raw)
    ProxyContext(raw_prompt=case.raw, detected_entities=detections).validate_detected_spans()
    L3Output(case.raw, tuple(detections))


@pytest.mark.parametrize("raw,expected", [(Z1, Z_EXPECTED[0]), (Z2, Z_EXPECTED[1])])
@pytest.mark.parametrize("entities", [["AGE"], ["AGE_GROUP"], ["AGE", "AGE_GROUP"], None])
def test_z_age_coexistence(service, raw, expected, entities):
    detections = service.analyze(raw, SEGMENT, entities=entities)
    wanted = sorted(item for item in expected if entities is None or item[0] in entities)
    actual = sorted((d.entity_type, d.start_idx, d.end_idx, d.original_value) for d in detections)
    assert actual == wanted
    for d in detections:
        assert d.normalized == d.original_value == raw[d.start_idx : d.end_idx]
        assert d.confidence is None
        assert d.tier is DetectionTier.RULE_ANCHORED
        assert d.source == (
            "AgeStatementRecognizer" if d.entity_type == "AGE" else "AgeGroupStatementRecognizer"
        )
    ProxyContext(raw_prompt=raw, detected_entities=detections).validate_detected_spans()


@pytest.mark.parametrize(
    "raw,entities",
    [
        ("고객은 32세입니다.", ["AGE_GROUP"]),
        (RAW, ["AGE"]),
        ("나이: 20대", ["AGE"]),
    ],
)
def test_z_no_derived_detection(service, raw, entities):
    assert service.analyze(raw, SEGMENT, entities=entities) == []


def test_z_refined_only_and_default_capability(service):
    for entities in (["AGE", "AGE_GROUP"], None):
        ds = service.analyze(REFINED, SEGMENT, entities=entities)
        assert [(d.entity_type, d.start_idx, d.end_idx) for d in ds] == [("AGE_GROUP", 4, 10)]


@pytest.mark.parametrize("segment", [SEGMENT, "h2-segment-99", "seg-1"])
def test_out_caller_segment_and_explicit_fields(service, segment):
    ds = service.analyze(RAW, segment, entities=["AGE_GROUP"])
    assert len(ds) == 1
    check_detection(ds[0], RAW, segment)


def test_aa06_adapter_preserves_second_duplicate_offset(service):
    r = result(service, REPEATED_START, REPEATED_START + 3)
    d = adapt_result(r, REPEATED, SEGMENT, service._analyzer.registry)
    check_detection(d, REPEATED)
    assert (d.start_idx, d.end_idx) == (REPEATED_START, REPEATED_START + 3)


@pytest.mark.parametrize("mutation", ["start", "original"])
def test_ctx_corrupted_span_pair(service, mutation):
    d = service.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0]
    d = d.model_copy(update={"start_idx": 5} if mutation == "start" else {"original_value": "40대"})
    with pytest.raises(ValueError, match="span mismatch"):
        ProxyContext(raw_prompt=RAW, detected_entities=[d]).validate_detected_spans()


@pytest.mark.parametrize("start,end", [(-1, 7), (4, 4), (7, 4), (4, len(RAW) + 1)])
def test_span_direct_and_service_recovery(isolated, start, end):
    r = result(isolated, start, end)
    with pytest.raises(DetectionValidationError, match="SPAN_BOUNDS"):
        adapt_result(r, RAW, SEGMENT, isolated._analyzer.registry)
    with (
        patch.object(isolated._analyzer, "analyze", return_value=[r]),
        pytest.raises(L3RuntimeError, match="L3_ANALYSIS_OR_ADAPTATION_FAILED"),
    ):
        isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    check_detection(isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0], RAW)


def test_seg_single_segment_boundary(service):
    ds = service.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])
    with pytest.raises(ValueError, match="MULTI_SEGMENT_NOT_IMPLEMENTED"):
        L3Output(REPEATED, (ds[0], ds[1].model_copy(update={"segment_id": "another"})))


@pytest.mark.parametrize(
    "field,value",
    [
        ("segment_id", "seg-1"),
        ("source", "unknown"),
        ("normalized", ""),
        *(("entity_type", alias) for alias in ALIASES),
        *(
            ("tier", tier)
            for tier in (DetectionTier.DETERMINISTIC, DetectionTier.MODEL, DetectionTier.CANDIDATE)
        ),
        *(("confidence", score) for score in (0, 0.0, 0.5, 1.0)),
    ],
)
def test_sc_conformance_negative_controls(service, field, value):
    payload = service.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0].model_dump()
    payload[field] = value
    with pytest.raises(AssertionError):
        check_payload(payload, RAW)


@pytest.mark.parametrize("key", FIELDS)
def test_sc_missing_key(service, key):
    payload = service.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0].model_dump()
    del payload[key]
    with pytest.raises(AssertionError):
        check_payload(payload, RAW)


def test_sc_extra_order_normalization_defaults(service):
    d = service.analyze("고객은 30대  초반입니다.", SEGMENT, entities=["AGE_GROUP"])[0]
    payload = d.model_dump()
    for invalid in (
        {**payload, "extra": PRIVATE},
        dict(reversed(list(payload.items()))),
        {**payload, "normalized": "30대 초반"},
    ):
        with pytest.raises(AssertionError):
            check_payload(invalid, "고객은 30대  초반입니다.")
    with pytest.raises(ValidationError) as caught:
        DetectedPII.model_validate({**payload, "extra": PRIVATE})
    assert PRIVATE not in str(caught.value)
    assert "input_value" not in str(caught.value)
    # Constructing with transitional defaults must fail even if a caller
    # happens to use seg-1; serialization by itself cannot prove explicitness.
    minimal = {k: v for k, v in payload.items() if k not in {"segment_id", "source", "normalized"}}
    defaulted = DetectedPII.model_validate(minimal)
    with pytest.raises(AssertionError):
        check_detection(defaulted, "고객은 30대  초반입니다.")


@pytest.mark.parametrize("entities", [[], ["EMAIL_ADDRESS"]])
def test_ab_unrequested(service, entities):
    assert service.analyze(RAW, SEGMENT, entities=entities) == []


def test_ab_duplicate_requests(service):
    assert len(service.analyze(RAW, SEGMENT, entities=["AGE_GROUP", "AGE_GROUP"])) == 1


@pytest.mark.parametrize("entity", UNSUPPORTED + ALIASES)
@pytest.mark.parametrize("mixed", [False, True])
def test_ab_unsupported_capability(service, entity, mixed):
    with pytest.raises(UnsupportedCapabilityError, match="UNSUPPORTED_ENTITY"):
        service.analyze(RAW, SEGMENT, entities=["AGE_GROUP", entity] if mixed else [entity])


def test_ab_language_and_input_contracts(service):
    with pytest.raises(UnsupportedCapabilityError, match="UNSUPPORTED_LANGUAGE"):
        service.analyze(RAW, SEGMENT, language="en")
    for raw, segment in ((None, SEGMENT), (RAW, ""), (RAW, " ")):
        with pytest.raises(ValueError):
            service.analyze(raw, segment)
    for entities in ("AGE_GROUP", [None]):
        with pytest.raises(UnsupportedCapabilityError, match="ENTITIES_TYPE"):
            service.analyze(RAW, SEGMENT, entities=entities)


def test_ac_exact_eleven_registry(service):
    registry = service._analyzer.registry
    producers = validate_registry(registry)
    assert len(registry.recognizers) == 11
    assert set(producers) == ENTITIES
    assert registry.supported_languages == ["ko"]
    p = producers["AGE_GROUP"]
    assert type(p) is AgeGroupStatementRecognizer
    assert p.supported_entities == ["AGE_GROUP"]
    assert p.supported_language == "ko"
    assert p.name == "AgeGroupStatementRecognizer"
    assert len({p.id for p in producers.values()}) == 11
    assert len(service.analyze(RAW, SEGMENT)) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "subclass",
        "duplicate",
        "missing",
        "producer_language",
        "registry_language",
        "entities",
        "empty_name",
        "layer_name",
        "empty_id",
    ],
)
@pytest.mark.parametrize("entities", [["AGE_GROUP"], []])
def test_ad_registry_faults(isolated, mutation, entities):
    registry = isolated._analyzer.registry
    p = producer(isolated)
    if mutation == "subclass":

        class UnverifiedGroup(AgeGroupStatementRecognizer):
            pass

        registry.recognizers[registry.recognizers.index(p)] = UnverifiedGroup()
    elif mutation == "duplicate":
        registry.recognizers.append(p)
    elif mutation == "missing":
        registry.recognizers.remove(p)
    elif mutation == "producer_language":
        p.supported_language = "en"
    elif mutation == "registry_language":
        registry.supported_languages = ["en"]
    elif mutation == "entities":
        p.supported_entities = ["AGE_GROUP", "AGE"]
    elif mutation == "empty_name":
        p.name = ""
    elif mutation == "layer_name":
        p.name = "L3"
    else:
        original_id = p.id
        with patch.object(type(p), "id", new_callable=PropertyMock, return_value="") as identity:
            assert type(p) is AgeGroupStatementRecognizer
            assert p.id == ""
            with pytest.raises(RegistryConfigurationError, match="PRODUCER_IDENTITY"):
                isolated.analyze(RAW, SEGMENT, entities=entities)
            identity.assert_called()
        assert p.id == original_id
        return
    with pytest.raises(RegistryConfigurationError):
        isolated.analyze(RAW, SEGMENT, entities=entities)


@pytest.mark.parametrize(
    "metadata",
    [
        {"recognizer_name": PRIVATE},
        {"recognizer_identifier": PRIVATE},
        PRIVATE,
        {"recognizer_name": ""},
        {"recognizer_identifier": ""},
    ],
)
def test_ad_provenance_boundaries_recovery_privacy(isolated, metadata, caplog):
    r = result(isolated)
    r.recognition_metadata = metadata
    with pytest.raises(ProvenanceError) as direct:
        adapt_result(r, RAW, SEGMENT, isolated._analyzer.registry)
    with (
        patch.object(isolated._analyzer, "analyze", return_value=[r]),
        pytest.raises(L3RuntimeError) as wrapped,
    ):
        isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    for value in (PRIVATE, RAW, "30대"):
        assert value not in str(direct.value)
        assert value not in str(wrapped.value)
        assert value not in caplog.text
    check_detection(isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0], RAW)


def test_ad_missing_metadata_baseline_fallback(service):
    r = result(service)
    r.recognition_metadata = None
    d = adapt_result(r, RAW, SEGMENT, service._analyzer.registry)
    check_detection(d, RAW)


@pytest.mark.parametrize("score", [0.01, 0.5, 1.0])
def test_ae_internal_score_independence(isolated, score):
    p = producer(isolated)
    original = p.analyze

    def rescore(*args, **kwargs):
        rs = original(*args, **kwargs)
        for r in rs:
            r.score = score
        return rs

    with patch.object(p, "analyze", side_effect=rescore):
        ds = isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    assert len(ds) == 1
    check_detection(ds[0], RAW)


@pytest.mark.parametrize("method", ["analyze", "_valid_candidate"])
@pytest.mark.parametrize("failure", [ValueError, RuntimeError])
def test_af_immediate_error_and_recovery(isolated, method, failure, caplog):
    p = producer(isolated)
    with (
        patch.object(p, method, side_effect=failure(PRIVATE)),
        pytest.raises(L3RuntimeError) as caught,
    ):
        isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    for secret in (PRIVATE, RAW, "30대"):
        assert secret not in str(caught.value)
        assert secret not in caplog.text
    check_detection(isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])[0], RAW)


@pytest.mark.parametrize("lazy", [False, True])
def test_af_regex_timeout_and_recovery(isolated, lazy, caplog):
    original = group_module._CANDIDATE
    matcher = Mock()

    def after_first(*args, **kwargs):
        yield next(original.finditer(*args, **kwargs))
        raise TimeoutError(PRIVATE)

    matcher.finditer.side_effect = after_first if lazy else TimeoutError(PRIVATE)
    with (
        patch.object(group_module, "_CANDIDATE", matcher),
        pytest.raises(L3DependencyTimeoutError) as caught,
    ):
        isolated.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])
    assert str(caught.value) == "L3_DEPENDENCY_TIMEOUT"
    assert PRIVATE not in caplog.text
    assert REPEATED not in caplog.text
    ds = isolated.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])
    assert [(d.start_idx, d.end_idx) for d in ds] == [(4, 7), (REPEATED_START, REPEATED_START + 3)]


@pytest.mark.parametrize("failure", [ValueError, TimeoutError])
def test_af_failure_after_first_candidate(isolated, failure, caplog):
    p = producer(isolated)
    original = p._valid_candidate
    calls = 0

    def validate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise failure(PRIVATE)
        return original(*args, **kwargs)

    expected = L3DependencyTimeoutError if failure is TimeoutError else L3RuntimeError
    with patch.object(p, "_valid_candidate", side_effect=validate), pytest.raises(expected):
        isolated.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])
    assert calls == 2
    assert PRIVATE not in caplog.text
    assert len(isolated.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])) == 2


def test_af_semantic_timeout(isolated):
    with (
        patch.object(producer(isolated), "_valid_candidate", side_effect=TimeoutError(PRIVATE)),
        pytest.raises(L3DependencyTimeoutError),
    ):
        isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    assert len(isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])) == 1


@pytest.mark.parametrize("group_first", [False, True])
@pytest.mark.parametrize("failure", [ValueError, TimeoutError])
def test_af_cross_entity_atomic_failure(isolated, group_first, failure, caplog):
    age, group = producer(isolated, "AGE"), producer(isolated)
    good, bad = (group, age) if group_first else (age, group)
    expected = L3DependencyTimeoutError if failure is TimeoutError else L3RuntimeError
    with (
        patch.object(isolated._analyzer.registry, "get_recognizers", return_value=[good, bad]),
        patch.object(good, "analyze", wraps=good.analyze) as succeeded,
        patch.object(bad, "_valid_candidate", side_effect=failure(PRIVATE)),
        patch("privacy_proxy.l3.service.adapt_result") as adapter,
        pytest.raises(expected),
    ):
        isolated.analyze(Z1, SEGMENT, entities=["AGE", "AGE_GROUP"])
    succeeded.assert_called_once()
    adapter.assert_not_called()
    assert PRIVATE not in caplog.text
    assert len(isolated.analyze(Z1, SEGMENT, entities=["AGE", "AGE_GROUP"])) == 2


def test_af_unrequested_and_initialization_failure(isolated):
    r = result(isolated)
    r.entity_type = "AGE"
    with (
        patch.object(isolated._analyzer, "analyze", return_value=[r]),
        pytest.raises(L3RuntimeError),
    ):
        isolated.analyze(RAW, SEGMENT, entities=["AGE_GROUP"])
    with (
        patch("privacy_proxy.l3.service.build_analyzer", side_effect=RuntimeError(PRIVATE)),
        pytest.raises(L3RuntimeError, match="ANALYZER_INITIALIZATION_FAILED"),
    ):
        L3AnalyzerService()


@pytest.mark.parametrize("raw", [RAW, REFINED, REPEATED])
def test_ag_success_logging(service, raw, caplog):
    ds = service.analyze(raw, SEGMENT, entities=["AGE_GROUP"])
    assert ds
    assert raw not in caplog.text
    for d in ds:
        assert d.original_value not in caplog.text


@pytest.mark.parametrize("raw", [RAW, REFINED])
async def test_aj_plain_refined_l5(service, raw):
    ds = service.analyze(raw, SEGMENT, entities=["AGE_GROUP"])
    feature = to_qi_feature(ds[0])
    assert feature.specificity == 1
    assert feature.base_score == 8
    before = [d.model_dump() for d in ds]
    ctx = await run_l5_risk_scoring(ProxyContext(raw_prompt=raw, detected_entities=ds))
    assert ctx.status == "success"
    assert ctx.risk_score == 8
    assert ctx.policy_action == "ALLOW"
    assert [d.model_dump() for d in ctx.detected_entities] == before


@pytest.mark.parametrize("with_dob", [False, True])
async def test_aj_age_dimension_keeps_detections(service, with_dob):
    raw = "나이: 32세, 연령대: 30대 초반, 생년월일: 1994-01-02"
    ds = service.analyze(raw, SEGMENT, entities=["AGE", "AGE_GROUP"])
    assert sorted((d.entity_type, d.original_value) for d in ds) == [
        ("AGE", "32세"),
        ("AGE_GROUP", "30대 초반"),
    ]
    if with_dob:
        start = len("나이: 32세, 연령대: 30대 초반, 생년월일: ")
        ds.append(
            DetectedPII(
                segment_id=SEGMENT,
                start_idx=start,
                end_idx=start + len("1994-01-02"),
                entity_type="DATE_OF_BIRTH",
                confidence=None,
                source="SyntheticDOBFixture",
                tier=DetectionTier.RULE_ANCHORED,
                original_value="1994-01-02",
                normalized="1994-01-02",
            )
        )
    before = sorted((d.start_idx, d.end_idx, d.entity_type, d.original_value) for d in ds)
    ctx = await run_l5_risk_scoring(ProxyContext(raw_prompt=raw, detected_entities=ds))
    assert ctx.status == "success"
    assert ctx.risk_score == (22 if with_dob else 20)
    assert len(ctx.risk_reasons) == 1
    assert (
        sorted(
            (d.start_idx, d.end_idx, d.entity_type, d.original_value) for d in ctx.detected_entities
        )
        == before
    )


async def test_aj_repeated_score_without_deleting_spans(service):
    ds = service.analyze(REPEATED, SEGMENT, entities=["AGE_GROUP"])
    ctx = await run_l5_risk_scoring(ProxyContext(raw_prompt=REPEATED, detected_entities=ds))
    assert ctx.status == "success"
    assert ctx.risk_score == 8
    assert len(ctx.detected_entities) == 2


@pytest.mark.parametrize("raw,value", [(RAW, "30대"), (REFINED, "30대 초반")])
@pytest.mark.parametrize("policy", ["TOKENIZE", "GENERALIZE"])
def test_aj_l6_existing_policy_and_private_mapping(service, raw, value, policy, caplog):
    crypto = VaultCrypto.from_base64(VaultCrypto.generate_key())
    tokenizer = Tokenizer(InMemoryVaultStore(crypto), crypto)
    ds = service.analyze(raw, SEGMENT, entities=["AGE_GROUP"])
    output = tokenizer.anonymize(
        session_id="h2-synthetic-session",
        raw_prompt=raw,
        detected_entities=ds,
        policy_action=policy,
    )
    if policy == "GENERALIZE":
        assert output.anonymized_prompt == raw
        assert output.vault_mapping == {}
    else:
        assert len(output.vault_mapping) == 1
        token, original = next(iter(output.vault_mapping.items()))
        assert original == value
        assert output.anonymized_prompt == "고객은 " + token + "입니다."
        assert tokenizer.reveal("h2-synthetic-session", token) == value
        assert token not in caplog.text
    assert raw not in caplog.text
    assert value not in caplog.text
    assert PRIVATE not in caplog.text


def test_ah_frozen_age_source_and_semantic_unit_hashes():
    root = Path(__file__).resolve().parents[2]
    expected = {
        "src/privacy_proxy/l3/age_recognizer.py": "7DC36A3335D235AC972F5170F3FA2A8C59982D78B93AF30506A1A2C7F407D39D",
        "tests/unit/test_age.py": "B6F2BCB25D7381D5B6FF6ECE055AEF3B372EC15149F8B8D70843BF6CE8C394C8",
    }
    for relative, digest in expected.items():
        assert sha256((root / relative).read_bytes()).hexdigest().upper() == digest


# Independent literal H3 regressions: do not derive these expectations from CASES
# or the unit suite's R2_REJECTIONS.
@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("연령대: 30대 인가요?", id="R2-F1-question-SEMANTIC_REJECTION"),
        pytest.param("연령대: 30대\t인가요?", id="R2-F1-tab-SEMANTIC_REJECTION"),
        pytest.param("연령대: 30대 초반 인가요?", id="R2-F1-refined-SEMANTIC_REJECTION"),
        pytest.param("연령대: 30대 이면 할인됩니다.", id="R2-F1-condition-SEMANTIC_REJECTION"),
        pytest.param("연령대: 30대 입니다만", id="R2-F1-ending-SEMANTIC_REJECTION"),
        pytest.param("연령대: 30대 초중반인가요?", id="R2-F2-question-DEFERRED_SCOPE"),
        pytest.param("연령대: 30대 중후반이면 할인됩니다.", id="R2-F2-condition-DEFERRED_SCOPE"),
        pytest.param("평균 연령대: 30대", id="R2-F3-statistics-SEMANTIC_REJECTION"),
        pytest.param("추천 대상 고객은 30대입니다.", id="R2-F3-target-SEMANTIC_REJECTION"),
    ],
)
def test_r2_h3_service_rejections(service, raw):
    assert service.analyze(raw, SEGMENT, entities=["AGE_GROUP"]) == []


@pytest.mark.parametrize(
    "raw,start",
    [
        ("연령대: 30대 인가요? 고객은 20대입니다.", len("연령대: 30대 인가요? 고객은 ")),
        ("연령대: 30대\t인가요? 고객은 20대입니다.", len("연령대: 30대\t인가요? 고객은 ")),
        (
            "연령대: 30대 초반 인가요? 고객은 20대입니다.",
            len("연령대: 30대 초반 인가요? 고객은 "),
        ),
        (
            "연령대: 30대 이면 할인됩니다. 고객은 20대입니다.",
            len("연령대: 30대 이면 할인됩니다. 고객은 "),
        ),
        ("연령대: 30대 입니다만. 고객은 20대입니다.", len("연령대: 30대 입니다만. 고객은 ")),
        (
            "연령대: 30대 초중반인가요? 고객은 20대입니다.",
            len("연령대: 30대 초중반인가요? 고객은 "),
        ),
        (
            "연령대: 30대 중후반이면 할인됩니다. 고객은 20대입니다.",
            len("연령대: 30대 중후반이면 할인됩니다. 고객은 "),
        ),
        ("평균 연령대: 30대. 고객은 20대입니다.", len("평균 연령대: 30대. 고객은 ")),
        (
            "추천 대상 고객은 30대입니다. 저는 20대입니다.",
            len("추천 대상 고객은 30대입니다. 저는 "),
        ),
        ("평균 연령대: 30대, 고객 연령대: 20대", len("평균 연령대: 30대, 고객 연령대: ")),
        ("평균 연령대: 30대; 고객 연령대: 20대", len("평균 연령대: 30대; 고객 연령대: ")),
        ("고객은 20대입니다. 추천 대상 고객은 30대입니다.", 4),
    ],
)
def test_r2_h3_service_locality(service, raw, start):
    ds = service.analyze(raw, SEGMENT, entities=["AGE_GROUP"])
    assert [(d.entity_type, d.start_idx, d.end_idx, d.original_value) for d in ds] == [
        ("AGE_GROUP", start, start + 3, "20대")
    ]
    check_detection(ds[0], raw)
    ProxyContext(raw_prompt=raw, detected_entities=ds).validate_detected_spans()


@pytest.mark.parametrize(
    "raw,start,end,value",
    [
        ("고객은 30대입니다.", 4, 7, "30대"),
        ("연령대: 30대", 5, 8, "30대"),
        ("연령대: 30대입니다", 5, 8, "30대"),
        ("연령대: 30대 입니다", 5, 8, "30대"),
        ("연령대: 30대 초반", 5, 11, "30대 초반"),
        ("연령대: 30대\t초반\t입니다", 5, 11, "30대\t초반"),
    ],
)
def test_r2_h3_service_positive_controls(service, raw, start, end, value):
    ds = service.analyze(raw, SEGMENT, entities=["AGE_GROUP"])
    assert [(d.start_idx, d.end_idx, d.original_value) for d in ds] == [(start, end, value)]
    check_detection(ds[0], raw)
    ProxyContext(raw_prompt=raw, detected_entities=ds).validate_detected_spans()
