import pytest

from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectionTier


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        (
            "30\ub300 \ucd08\ubc18\uc774\uc5d0\uc694",
            "30\ub300 \ucd08\ubc18",
        ),
        (
            "30\ub300 \uc5ec\uc131\uc774\uace0",
            "30\ub300",
        ),
    ),
)
def test_runtime_bare_personal_age_group_is_detected(
    raw: str,
    expected: str,
) -> None:
    service = L3AnalyzerService()

    detections = service.analyze(
        raw_prompt=raw,
        segment_id="seg-age-group-personal",
        entities=["AGE_GROUP"],
    )

    assert len(detections) == 1

    detection = detections[0]

    assert detection.start_idx == 0
    assert detection.end_idx == len(expected)

    assert raw[detection.start_idx : detection.end_idx] == expected

    assert detection.original_value == expected
    assert detection.normalized == expected

    assert detection.entity_type == "AGE_GROUP"
    assert detection.source == "AgeGroupStatementRecognizer"
    assert detection.confidence is None
    assert detection.tier is DetectionTier.RULE_ANCHORED


@pytest.mark.parametrize(
    "raw",
    (
        "\ud3c9\uade0 \uc5f0\ub839\uc740 30\ub300 \ucd08\ubc18\uc774\uc5d0\uc694",
        "\ud3c9\uade0 \uc5f0\ub839\ub300\ub294 30\ub300\uc785\ub2c8\ub2e4",
        "30\ub300 \uace0\uac1d\uc774 \ub9ce\uc774 \ucc3e\uc2b5\ub2c8\ub2e4",
        "30\ub300 \uace0\uac1d\uc774 \ub9ce\uc544\uc694",
        "30\ub300 \uc5ec\uc131\uc774\uace0 \uad6c\ub9e4\uc728\uc774 \ub192\uc2b5\ub2c8\ub2e4",
        "30\ub300 \uc5ec\uc131\uc774\uace0 \uc8fc\uc694 \uace0\uac1d\uce35\uc785\ub2c8\ub2e4",
    ),
)
def test_runtime_bare_age_group_does_not_broaden_nonpersonal_context(
    raw: str,
) -> None:
    service = L3AnalyzerService()

    detections = service.analyze(
        raw_prompt=raw,
        segment_id="seg-age-group-negative",
        entities=["AGE_GROUP"],
    )

    assert detections == []
