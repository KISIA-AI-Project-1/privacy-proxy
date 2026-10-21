import pytest

from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectionTier

EMAIL = "audit+tag@example.com"
LABEL = "\uc774\uba54\uc77c"
SUFFIX = "\uc785\ub2c8\ub2e4"

EXPECTED_KEYS = {
    "segment_id",
    "start_idx",
    "end_idx",
    "entity_type",
    "confidence",
    "source",
    "tier",
    "original_value",
    "normalized",
    "anchor_text",
    "anchor_start",
    "anchor_end",
}


def assert_runtime_email(
    service: L3AnalyzerService,
    raw: str,
    expected: str,
    expected_start: int,
) -> None:
    detections = service.analyze(
        raw_prompt=raw,
        segment_id="seg-email-left-boundary",
        entities=["EMAIL_ADDRESS"],
    )

    assert len(detections) == 1

    detection = detections[0]
    expected_end = expected_start + len(expected)

    assert detection.start_idx == expected_start
    assert detection.end_idx == expected_end

    assert raw[detection.start_idx : detection.end_idx] == expected
    assert detection.original_value == expected
    assert detection.normalized == expected

    assert detection.entity_type == "EMAIL_ADDRESS"
    assert detection.source == "EmailRecognizer"
    assert detection.confidence is None
    assert detection.tier is DetectionTier.RULE_ANCHORED

    assert set(detection.model_dump()) == EXPECTED_KEYS


@pytest.mark.parametrize(
    "raw",
    (
        LABEL + EMAIL,
        LABEL + EMAIL + SUFFIX,
    ),
)
def test_runtime_known_label_is_outside_email_span(raw: str) -> None:
    service = L3AnalyzerService()

    assert_runtime_email(
        service,
        raw,
        EMAIL,
        len(LABEL),
    )


def test_runtime_multi_entity_chain_keeps_email_boundary() -> None:
    service = L3AnalyzerService()

    passport = "M123A4567"

    raw = "\uc5ec\uad8c" + passport + "\uc774\uace0" + LABEL + EMAIL + SUFFIX

    detections = service.analyze(
        raw_prompt=raw,
        segment_id="seg-email-chain",
        entities=[
            "KR_PASSPORT",
            "EMAIL_ADDRESS",
        ],
    )

    assert len(detections) == 2

    by_type = {detection.entity_type: detection for detection in detections}

    assert set(by_type) == {
        "KR_PASSPORT",
        "EMAIL_ADDRESS",
    }

    passport_detection = by_type["KR_PASSPORT"]
    email_detection = by_type["EMAIL_ADDRESS"]

    passport_start = raw.index(passport)
    email_start = raw.index(EMAIL)

    assert passport_detection.start_idx == passport_start
    assert passport_detection.end_idx == passport_start + len(passport)
    assert passport_detection.original_value == passport

    assert email_detection.start_idx == email_start
    assert email_detection.end_idx == email_start + len(EMAIL)
    assert email_detection.original_value == EMAIL

    assert raw[email_detection.start_idx : email_detection.end_idx] == EMAIL


def test_runtime_existing_right_suffix_still_passes() -> None:
    service = L3AnalyzerService()

    raw = EMAIL + SUFFIX

    assert_runtime_email(
        service,
        raw,
        EMAIL,
        0,
    )


@pytest.mark.parametrize(
    "expected",
    (
        "\ud64d\uae38\ub3d9\uba54\uc77caudit@example.com",
        "foo\uba54\uc77caudit@example.com",
        "foo\uc774\uba54\uc77caudit@example.com",
    ),
)
def test_runtime_embedded_label_text_is_not_trimmed(
    expected: str,
) -> None:
    service = L3AnalyzerService()

    assert_runtime_email(
        service,
        expected,
        expected,
        0,
    )
