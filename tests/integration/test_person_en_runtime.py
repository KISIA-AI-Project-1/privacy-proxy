"""R6 PERSON_EN explicit-request runtime contract.

The bootstrap registry test is intentionally RED before production
wiring exists. Behavior tests are blocked until both the module and
registry entry exist.

Default-request widening is intentionally outside R6-S3B.
"""

from importlib.util import find_spec

import pytest

from privacy_proxy.l3.registry import SUPPORTED_ENTITIES
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectionTier

MODULE_NAME = "privacy_proxy.l3.person_en_recognizer"
MODULE_PRESENT = find_spec(MODULE_NAME) is not None

RUNTIME_READY = MODULE_PRESENT and "PERSON_EN" in SUPPORTED_ENTITIES

requires_person_en_runtime = pytest.mark.skipif(
    not RUNTIME_READY,
    reason="blocked until PERSON_EN module and registry wiring exist",
)


def test_r6_red_person_en_registered() -> None:
    assert "PERSON_EN" in SUPPORTED_ENTITIES, "RED_PERSON_EN_NOT_REGISTERED"


@pytest.fixture(scope="module")
def service() -> L3AnalyzerService:
    return L3AnalyzerService()


def detect(
    service: L3AnalyzerService,
    text: str,
):
    return service.analyze(
        text,
        "r6-person-en-contract",
        entities=["PERSON_EN"],
    )


def one(
    service: L3AnalyzerService,
    text: str,
):
    detections = detect(
        service,
        text,
    )

    assert len(detections) == 1

    detection = detections[0]

    assert text[detection.start_idx : detection.end_idx] == detection.original_value

    return detection


@requires_person_en_runtime
def test_person_en_canonical_schema(
    service: L3AnalyzerService,
) -> None:
    text = "John Smith contacted support."

    detection = one(
        service,
        text,
    )

    assert detection.entity_type == "PERSON_EN"
    assert detection.original_value == "John Smith"
    assert detection.normalized == "John Smith"
    assert detection.confidence is None
    assert detection.tier is DetectionTier.MODEL
    assert detection.source == "PersonEnRecognizer"


@requires_person_en_runtime
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "John Smith contacted support.",
            "John Smith",
        ),
        (
            "The customer is Alice Brown.",
            "Alice Brown",
        ),
        (
            "Dr. John Smith contacted support.",
            "John Smith",
        ),
        (
            "Mary-Jane Watson requested a refund.",
            "Mary-Jane Watson",
        ),
        (
            "Patrick O'Neil requested support.",
            "Patrick O'Neil",
        ),
        (
            "John A. Smith requested support.",
            "John A. Smith",
        ),
        (
            "Minsoo Kim contacted support.",
            "Minsoo Kim",
        ),
    ],
)
def test_person_en_positive_contract(
    service: L3AnalyzerService,
    text: str,
    expected: str,
) -> None:
    detection = one(
        service,
        text,
    )

    assert detection.original_value == expected
    assert detection.start_idx == text.index(expected)
    assert detection.end_idx == (text.index(expected) + len(expected))


@requires_person_en_runtime
@pytest.mark.parametrize(
    "text",
    [
        "John Smith's package has shipped.",
        "John Smith\u2019s package has shipped.",
    ],
)
def test_person_en_possessive_suffix_is_excluded(
    service: L3AnalyzerService,
    text: str,
) -> None:
    detection = one(
        service,
        text,
    )

    assert detection.original_value == "John Smith"
    assert detection.start_idx == 0
    assert detection.end_idx == len("John Smith")


@requires_person_en_runtime
@pytest.mark.parametrize(
    "text",
    [
        "John Smith\uc640 \uae40\ubbfc\uc218\uac00 \ubb38\uc758\ud588\uc2b5\ub2c8\ub2e4.",
        "John Smith\uc5d0\uac8c \ubb38\uc758\ud588\uc2b5\ub2c8\ub2e4.",
        "John Smith\uc73c\ub85c \uae30\ub85d\ud588\uc2b5\ub2c8\ub2e4.",
    ],
)
def test_person_en_approved_korean_postposition_is_excluded(
    service: L3AnalyzerService,
    text: str,
) -> None:
    detection = one(
        service,
        text,
    )

    assert detection.original_value == "John Smith"
    assert detection.start_idx == 0
    assert detection.end_idx == len("John Smith")


@requires_person_en_runtime
@pytest.mark.parametrize(
    "text",
    [
        "\uae40\ubbfc\uc218\uac00 "
        "\uace0\uac1d\uc13c\ud130\uc5d0 "
        "\ubb38\uc758\ud588\uc2b5\ub2c8\ub2e4.",
        "\uae40\ubbfc\uc218 contacted support.",
    ],
)
def test_person_en_does_not_claim_hangul_person_surface(
    service: L3AnalyzerService,
    text: str,
) -> None:
    assert (
        detect(
            service,
            text,
        )
        == []
    )


@requires_person_en_runtime
@pytest.mark.parametrize(
    "text",
    [
        "Microsoft released an update.",
        "Seattle has heavy rain today.",
        "The order number is 12345678.",
    ],
)
def test_person_en_negative_boundaries(
    service: L3AnalyzerService,
    text: str,
) -> None:
    assert (
        detect(
            service,
            text,
        )
        == []
    )


@requires_person_en_runtime
def test_person_ko_remains_outside_l3_ownership() -> None:
    assert "PERSON_KO" not in SUPPORTED_ENTITIES
