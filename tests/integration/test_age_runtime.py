"""D7 service, failure and shadow-boundary tests with synthetic fixtures."""

from unittest.mock import Mock, patch

import pytest

from privacy_proxy.integration.l3_output import L3Output
from privacy_proxy.l3 import age_recognizer as age_module
from privacy_proxy.l3.age_recognizer import AgeStatementRecognizer
from privacy_proxy.l3.registry import RegistryConfigurationError, validate_registry
from privacy_proxy.l3.service import L3AnalyzerService, L3RuntimeError, UnsupportedCapabilityError
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError
from privacy_proxy.schemas import DetectedPII, DetectionTier
from tests.fixtures import BRN_VALID, KEYS, PASSPORT
from tests.integration.test_dependency_timeout import timeout_patterns

ORIGINAL_ENTITIES = {
    "KR_RRN",
    "KR_FRN",
    "KR_PASSPORT",
    "KR_DRIVER_LICENSE",
    "KR_BRN",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
}


@pytest.fixture
def service():
    return L3AnalyzerService()


def check_detection(detection, raw, producer, segment="s"):
    assert isinstance(detection, DetectedPII)
    payload = detection.model_dump()
    assert set(payload) == KEYS
    assert tuple(payload) == tuple(DetectedPII.model_fields)
    assert DetectedPII.model_validate(payload).model_dump() == payload
    assert detection.model_dump(mode="json")["tier"] == DetectionTier.RULE_ANCHORED.value
    assert detection.entity_type == "AGE"
    assert detection.segment_id == segment
    assert 0 <= detection.start_idx < detection.end_idx <= len(raw)
    assert raw[detection.start_idx : detection.end_idx] == detection.original_value
    assert detection.normalized == detection.original_value
    assert detection.confidence is None
    assert detection.source == producer.name
    assert detection.tier is DetectionTier.RULE_ANCHORED


@pytest.mark.parametrize(
    ("raw", "surface"),
    [
        ("고객 나이는 32세입니다.", "32세"),
        ("나이: 32세", "32세"),
        ("연령은 만 19세입니다.", "만 19세"),
        ("고객 연령은 45 살입니다.", "45 살"),
        ("저는 25살입니다.", "25살"),
        ("제가 25살입니다.", "25살"),
        ("고객은 32세입니다.", "32세"),
        ("제 나이는 만 19세 입니다.", "만 19세"),
        ("고객 연령은 32 세입니다.", "32 세"),
        ("한글😀! 나이:\t만\t19\t세.", "만\t19\t세"),
    ],
)
def test_real_service_contract_and_shadow(service, raw, surface):
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    producer = validate_registry(service._analyzer.registry)["AGE"]
    check_detection(detections[0], raw, producer)
    assert detections[0].original_value == surface
    output = L3Output(raw, tuple(detections))
    assert output.detections[0].model_dump() == detections[0].model_dump()


def test_eleven_unique_default_capabilities(service):
    producers = validate_registry(service._analyzer.registry)
    assert set(producers) == ORIGINAL_ENTITIES | {"AGE", "AGE_GROUP", "DATE_OF_BIRTH", "LOCATION"}
    assert type(producers["AGE"]) is AgeStatementRecognizer
    assert producers["AGE"].supported_language == "ko"
    assert producers["AGE"].name == "AgeStatementRecognizer"
    assert len(service.analyze("나이: 32세", "s", entities=["AGE"])) == 1
    assert service.analyze("나이: 32세", "s", entities=[]) == []
    assert service.analyze("나이: 32세", "s", entities=["KR_PASSPORT"]) == []


@pytest.mark.parametrize("entity", ["PERSON_EN", "ADDRESS"])
def test_other_capabilities_stay_unsupported(service, entity):
    with pytest.raises(UnsupportedCapabilityError):
        service.analyze("", "s", entities=[entity])


@pytest.mark.parametrize("mutation", ["duplicate", "language", "type"])
def test_registry_still_validates_age(service, mutation):
    registry = service._analyzer.registry
    age = validate_registry(registry)["AGE"]
    if mutation == "duplicate":
        registry.recognizers.append(age)
    elif mutation == "language":
        age.supported_language = "en"
    else:

        class UnverifiedAge(AgeStatementRecognizer):
            pass

        registry.recognizers[-1] = UnverifiedAge()
    with pytest.raises(RegistryConfigurationError):
        service.analyze("나이: 32세", "s")


def test_multiple_offsets_single_segment(service):
    raw = "😀 나이: 32세. 저는 32세입니다! 연령은 만 19 세입니다."
    detections = sorted(service.analyze(raw, "s", entities=["AGE"]), key=lambda d: d.start_idx)
    producer = validate_registry(service._analyzer.registry)["AGE"]
    assert [d.original_value for d in detections] == ["32세", "32세", "만 19 세"]
    assert len({d.start_idx for d in detections}) == 3
    for detection in detections:
        check_detection(detection, raw, producer)
    L3Output(raw, tuple(detections))
    other = DetectedPII.model_validate({**detections[1].model_dump(), "segment_id": "other"})
    with pytest.raises(ValueError, match="MULTI_SEGMENT"):
        L3Output(raw, (detections[0], other))


def test_mixed_success(service):
    raw = "나이: 32세. " + PASSPORT + " audit@example.com"
    detections = service.analyze(raw, "s", entities=["AGE", "KR_PASSPORT", "EMAIL_ADDRESS"])
    assert {d.entity_type for d in detections} == {"AGE", "KR_PASSPORT", "EMAIL_ADDRESS"}
    for detection in detections:
        assert raw[detection.start_idx : detection.end_idx] == detection.original_value
    L3Output(raw, tuple(detections))


@pytest.mark.parametrize("failure", [ValueError, RuntimeError, TimeoutError])
def test_failure_after_candidate_is_explicit_and_next_request_recovers(service, failure, caplog):
    age = validate_registry(service._analyzer.registry)["AGE"]
    raw = "나이: 32세"
    with patch.object(age, "_valid_candidate", side_effect=failure("SYNTHETIC_PRIVATE_ERROR")):
        expected = L3DependencyTimeoutError if failure is TimeoutError else L3RuntimeError
        with pytest.raises(expected) as caught:
            service.analyze(raw, "s", entities=["AGE"])
    assert "SYNTHETIC_PRIVATE_ERROR" not in str(caught.value)
    assert raw not in str(caught.value)
    assert "SYNTHETIC_PRIVATE_ERROR" not in caplog.text
    assert raw not in caplog.text
    assert len(service.analyze(raw, "s", entities=["AGE"])) == 1


def test_immediate_recognizer_exception(service):
    age = validate_registry(service._analyzer.registry)["AGE"]
    with (
        patch.object(age, "analyze", side_effect=RuntimeError("PRIVATE")),
        pytest.raises(L3RuntimeError, match="L3_ANALYSIS_OR_ADAPTATION_FAILED"),
    ):
        service.analyze("나이: 32세", "s", entities=["AGE"])


@pytest.mark.parametrize("lazy", [False, True])
def test_regex_timeout_immediate_or_after_first_match(service, lazy):
    original = age_module._CANDIDATE
    raw = "나이: 32세 저는 25살입니다"
    matcher = Mock()

    def after_match(*args, **kwargs):
        yield next(original.finditer(*args, **kwargs))
        raise TimeoutError("PRIVATE")

    matcher.finditer.side_effect = after_match if lazy else TimeoutError("PRIVATE")
    with (
        patch.object(age_module, "_CANDIDATE", matcher),
        pytest.raises(L3DependencyTimeoutError),
    ):
        service.analyze(raw, "s", entities=["AGE"])
    assert len(service.analyze("나이: 32세", "s", entities=["AGE"])) == 1


@pytest.mark.parametrize("age_first", [False, True])
def test_cross_entity_failure_is_atomic(service, age_first):
    registry = service._analyzer.registry
    producers = validate_registry(registry)
    age, brn = producers["AGE"], producers["KR_BRN"]
    raw = "나이: 32세. " + BRN_VALID
    order = [age, brn] if age_first else [brn, age]
    good = age if age_first else brn
    failure = (
        timeout_patterns(service, "KR_BRN")
        if age_first
        else patch.object(age, "_valid_candidate", side_effect=TimeoutError("PRIVATE"))
    )
    with (
        patch.object(registry, "get_recognizers", return_value=order),
        patch.object(good, "analyze", wraps=good.analyze) as successful,
        patch("privacy_proxy.l3.service.adapt_result") as adapter,
        failure,
    ):
        with pytest.raises(L3DependencyTimeoutError):
            service.analyze(raw, "s", entities=["AGE", "KR_BRN"])
        successful.assert_called_once()
        adapter.assert_not_called()
    assert {d.entity_type for d in service.analyze(raw, "s", entities=["AGE", "KR_BRN"])} == {
        "AGE",
        "KR_BRN",
    }


def test_age_tier_is_not_internal_score(service):
    age = validate_registry(service._analyzer.registry)["AGE"]
    raw = "나이: 32세"
    original = age.analyze

    def rescore(*args, **kwargs):
        results = original(*args, **kwargs)
        for result in results:
            result.score = 0.01
        return results

    with patch.object(age, "analyze", side_effect=rescore):
        detection = service.analyze(raw, "s", entities=["AGE"])[0]
    check_detection(detection, raw, age)


@pytest.mark.parametrize(
    "raw",
    [
        "나이: 30세 내외",
        "나이: 30세 안팎",
        "가입 연령은 18세입니다.",
        "권장 연령은 12세입니다.",
        "나이는 5살 더 많습니다.",
    ],
)
def test_review_blocker_regression_service(service, raw):
    assert service.analyze(raw, "s", entities=["AGE"]) == []


@pytest.mark.parametrize(
    ("raw", "surface"),
    [
        ("가입 연령은 18세입니다. 고객 연령은 32세입니다.", "32세"),
        ("나이는 30세 내외입니다. 고객 나이는 42세입니다.", "42세"),
        ("형보다 5살 더 많습니다. 제 나이는 30세입니다.", "30세"),
    ],
)
def test_remediation_mixed_clause_contract(service, raw, surface):
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    producer = validate_registry(service._analyzer.registry)["AGE"]
    check_detection(detections[0], raw, producer)
    assert detections[0].original_value == surface
    output = L3Output(raw, tuple(detections))
    assert output.detections[0].model_dump() == detections[0].model_dump()


def test_pre_anchor_approximation_service_locality(service):
    raw = "대략 나이는 30세입니다. 고객 연령은 32세입니다."
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    assert detections[0].original_value == "32세"
    check_detection(detections[0], raw, validate_registry(service._analyzer.registry)["AGE"])


@pytest.mark.parametrize(
    "raw",
    ["고객 나이: 32세 적립금: 1000원", "고객 나이: 32세 적성: 음악"],
)
def test_d2_prefix_collision_service(service, raw):
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    assert detections[0].original_value == "32세"
    producer = validate_registry(service._analyzer.registry)["AGE"]
    check_detection(detections[0], raw, producer)
    output = L3Output(raw, tuple(detections))
    assert output.detections[0].model_dump() == detections[0].model_dump()


@pytest.mark.parametrize(
    "raw",
    [
        "나이는 5살 더 많았어요.",
        "나이는 5살 더 적지만 성인입니다.",
        "나이는 5살 더 많지만 학생입니다.",
    ],
)
def test_d3_comparative_structure_service(service, raw):
    assert service.analyze(raw, "s", entities=["AGE"]) == []


def test_d3_prefix_collision_service(service):
    raw = "고객 나이: 32세 적응 상태: 양호"
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    assert detections[0].original_value == "32세"
    check_detection(detections[0], raw, validate_registry(service._analyzer.registry)["AGE"])
    assert L3Output(raw, tuple(detections)).detections[0].model_dump() == detections[0].model_dump()


@pytest.mark.parametrize(
    "raw",
    [
        "고객 나이: 32세 더 적응이 필요합니다.",
        "고객 나이: 32세 더 적극적인 안내가 필요합니다.",
        "고객 나이: 32세 더 적절한 안내가 필요합니다.",
    ],
)
def test_d4_lexical_collision_service(service, raw):
    detections = service.analyze(raw, "s", entities=["AGE"])
    assert len(detections) == 1
    assert detections[0].original_value == "32세"
    check_detection(detections[0], raw, validate_registry(service._analyzer.registry)["AGE"])
    assert L3Output(raw, tuple(detections)).detections[0].model_dump() == detections[0].model_dump()
