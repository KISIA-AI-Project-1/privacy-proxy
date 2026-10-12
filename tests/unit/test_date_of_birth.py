"""R4-1D DATE_OF_BIRTH tests derived from the frozen behavior contract."""

from datetime import date

import pytest
from presidio_analyzer import RecognizerResult

import privacy_proxy.l3.date_of_birth_recognizer as dob_module
from privacy_proxy.l3.date_of_birth_recognizer import DateOfBirthRecognizer
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError

ENTITY = "DATE_OF_BIRTH"


def _analyze(
    text: str,
    entities: list[str] | None = None,
) -> list[RecognizerResult]:
    requested = [ENTITY] if entities is None else entities
    return DateOfBirthRecognizer().analyze(text, requested)


def _assert_one(text: str, expected_surface: str) -> RecognizerResult:
    results = _analyze(text)

    assert len(results) == 1

    result = results[0]

    assert isinstance(result, RecognizerResult)
    assert result.entity_type == ENTITY
    assert 0 <= result.start < result.end <= len(text)
    assert text[result.start : result.end] == expected_surface

    return result


# ---------------------------------------------------------------------------
# Producer capability
# ---------------------------------------------------------------------------


def test_exact_producer_identity() -> None:
    producer = DateOfBirthRecognizer()

    assert producer.name == "DateOfBirthRecognizer"


def test_exact_supported_entity() -> None:
    producer = DateOfBirthRecognizer()

    assert producer.supported_entities == [ENTITY]


def test_exact_supported_language() -> None:
    producer = DateOfBirthRecognizer()

    assert producer.supported_language == "ko"


@pytest.mark.parametrize(
    "entities",
    [
        [],
        ["AGE"],
        ["EMAIL_ADDRESS"],
    ],
)
def test_wrong_requested_entity_returns_no_result(entities: list[str]) -> None:
    assert (
        DateOfBirthRecognizer().analyze(
            "생년월일 2004-01-02",
            entities,
        )
        == []
    )


# ---------------------------------------------------------------------------
# Positive surfaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        ("생년월일 2004-01-02", "2004-01-02"),
        ("생년월일 20040102", "20040102"),
        ("생년월일 2004년 1월 2일", "2004년 1월 2일"),
        ("생년월일은 2004년 01월 02일입니다.", "2004년 01월 02일"),
        ("생일은 2004-01-02입니다.", "2004-01-02"),
        ("2004년 1월 2일생입니다.", "2004년 1월 2일"),
        ("생년월일은 2004-01-02입니다.", "2004-01-02"),
    ],
)
def test_supported_positive_surfaces(text: str, surface: str) -> None:
    _assert_one(text, surface)


# ---------------------------------------------------------------------------
# Approved prefix relations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        ("생년월일 2004-01-02", "2004-01-02"),
        ("생년월일: 2004-01-02", "2004-01-02"),
        ("생년월일 = 20040102", "20040102"),
        ("생년월일은 2004-01-02", "2004-01-02"),
        ("생년월일은: 2004-01-02", "2004-01-02"),
        ("생일은 2004년 1월 2일", "2004년 1월 2일"),
        ("생년월일\t2004-01-02", "2004-01-02"),
    ],
)
def test_approved_prefix_relations(text: str, surface: str) -> None:
    _assert_one(text, surface)


@pytest.mark.parametrize("particle", ["은", "는", "이"])
def test_approved_particles(particle: str) -> None:
    _assert_one(
        f"생년월일{particle} 2004-01-02",
        "2004-01-02",
    )


@pytest.mark.parametrize("delimiter", [":", "="])
def test_approved_delimiters(delimiter: str) -> None:
    _assert_one(
        f"생년월일{delimiter} 2004-01-02",
        "2004-01-02",
    )


@pytest.mark.parametrize("whitespace", [" ", "\t"])
def test_approved_horizontal_whitespace(whitespace: str) -> None:
    _assert_one(
        f"생년월일{whitespace}2004-01-02",
        "2004-01-02",
    )


# ---------------------------------------------------------------------------
# Bare and non-birth rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2004-01-02",
        "20040102",
        "2004년 1월 2일",
    ],
)
def test_bare_date_is_rejected(text: str) -> None:
    assert _analyze(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "주문일은 2004-01-02입니다.",
        "접수일은 2004-01-02입니다.",
        "계약일은 2004-01-02입니다.",
        "배송일은 2004-01-02입니다.",
    ],
)
def test_non_birth_date_context_is_rejected(text: str) -> None:
    assert _analyze(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "생년월일이 아니라 주문일은 2004-01-02입니다.",
        "생년월일 관련 문의입니다. 주문일은 2004-01-02입니다.",
    ],
)
def test_unrelated_birth_word_does_not_elevate_date(text: str) -> None:
    assert _analyze(text) == []


# ---------------------------------------------------------------------------
# Distance / relation boundaries
# ---------------------------------------------------------------------------


def test_anchor_distance_one_is_inclusive() -> None:
    text = "생년월일" + " " + "2004-01-02"

    assert text.index("2004-01-02") - len("생년월일") == 1
    _assert_one(text, "2004-01-02")


def test_anchor_distance_fifteen_is_inclusive() -> None:
    text = "생년월일" + (" " * 15) + "2004-01-02"

    assert text.index("2004-01-02") - len("생년월일") == 15
    _assert_one(text, "2004-01-02")


def test_anchor_distance_sixteen_is_rejected() -> None:
    text = "생년월일" + (" " * 16) + "2004-01-02"

    assert _analyze(text) == []


def test_anchor_distance_zero_is_rejected() -> None:
    assert _analyze("생년월일2004-01-02") == []


@pytest.mark.parametrize(
    "text",
    [
        "생년월일은은 2004-01-02",
        "생년월일:: 2004-01-02",
        "생년월일== 2004-01-02",
    ],
)
def test_repeated_particle_or_delimiter_is_rejected(text: str) -> None:
    assert _analyze(text) == []


@pytest.mark.parametrize(
    "separator",
    [
        "\r",
        "\n",
        "\r\n",
        ".",
        "!",
        "?",
    ],
)
def test_birth_anchor_cannot_cross_clause(separator: str) -> None:
    text = "생년월일" + separator + "2004-01-02"

    assert _analyze(text) == []


# ---------------------------------------------------------------------------
# Gregorian calendar validity
# ---------------------------------------------------------------------------


def test_valid_leap_date_is_emitted() -> None:
    _assert_one(
        "생년월일 2004-02-29",
        "2004-02-29",
    )


@pytest.mark.parametrize(
    "text",
    [
        "생년월일 2004-02-30",
        "생년월일 2003-02-29",
        "생년월일 2004-13-01",
        "생년월일 2004-01-00",
    ],
)
def test_invalid_gregorian_date_is_rejected(text: str) -> None:
    assert _analyze(text) == []


# ---------------------------------------------------------------------------
# UTC evaluation-date boundary
# ---------------------------------------------------------------------------


def test_past_date_is_allowed_with_frozen_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dob_module,
        "_utc_today",
        lambda: date(2026, 10, 8),
    )

    _assert_one(
        "생년월일 2004-01-02",
        "2004-01-02",
    )


def test_date_equal_to_evaluation_date_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dob_module,
        "_utc_today",
        lambda: date(2026, 10, 8),
    )

    _assert_one(
        "생년월일 2026-10-08",
        "2026-10-08",
    )


def test_future_date_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        dob_module,
        "_utc_today",
        lambda: date(2026, 10, 8),
    )

    assert _analyze("생년월일 2026-10-09") == []


# ---------------------------------------------------------------------------
# Partial dates / numeric boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "생년월일 2004년",
        "생년월일 1월 2일",
        "생년월일 2004-01",
    ],
)
def test_partial_date_is_rejected(text: str) -> None:
    assert _analyze(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "생년월일 1200401023",
        "생년월일 99120040102123",
        "생년월일 12004-01-02",
        "생년월일 2004-01-023",
    ],
)
def test_date_is_not_extracted_from_longer_numeric_surface(text: str) -> None:
    assert _analyze(text) == []


# ---------------------------------------------------------------------------
# Suffix behavior
# ---------------------------------------------------------------------------


def test_korean_native_birth_suffix_is_supported() -> None:
    _assert_one(
        "2004년 1월 2일생입니다.",
        "2004년 1월 2일",
    )


@pytest.mark.parametrize(
    "text",
    [
        "2004-01-02생입니다.",
        "20040102생입니다.",
    ],
)
def test_unapproved_numeric_birth_suffix_is_rejected(text: str) -> None:
    assert _analyze(text) == []


def test_hangul_after_iso_surface_does_not_break_detection() -> None:
    _assert_one(
        "생년월일은 2004-01-02입니다.",
        "2004-01-02",
    )


# ---------------------------------------------------------------------------
# Span / duplicate behavior
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        ("생년월일은 2004-01-02입니다.", "2004-01-02"),
        ("생년월일: 20040102", "20040102"),
        ("생일은 2004년 1월 2일입니다.", "2004년 1월 2일"),
        ("2004년 1월 2일생입니다.", "2004년 1월 2일"),
    ],
)
def test_result_span_is_exact_raw_date_surface(
    text: str,
    surface: str,
) -> None:
    result = _assert_one(text, surface)

    assert result.start == text.index(surface)
    assert result.end == result.start + len(surface)


def test_prefix_and_suffix_evidence_do_not_duplicate_same_span() -> None:
    text = "생년월일 2004년 1월 2일생입니다."

    results = _analyze(text)

    assert len(results) == 1
    assert text[results[0].start : results[0].end] == "2004년 1월 2일"


# ---------------------------------------------------------------------------
# Recognition metadata / provenance
# ---------------------------------------------------------------------------


def test_recognizer_metadata_identifies_actual_producer() -> None:
    producer = DateOfBirthRecognizer()

    results = producer.analyze(
        "생년월일 2004-01-02",
        [ENTITY],
    )

    assert len(results) == 1

    result = results[0]

    assert result.recognition_metadata is not None
    assert result.recognition_metadata[RecognizerResult.RECOGNIZER_NAME_KEY] == producer.name
    assert result.recognition_metadata[RecognizerResult.RECOGNIZER_IDENTIFIER_KEY] == producer.id


# ---------------------------------------------------------------------------
# Timeout / failure observability
# ---------------------------------------------------------------------------


def test_timeout_remains_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout_boundary(callback):
        def wrapped(*args, **kwargs):
            raise L3DependencyTimeoutError()

        return wrapped

    monkeypatch.setattr(
        dob_module,
        "protect_callable",
        timeout_boundary,
    )

    with pytest.raises(
        L3DependencyTimeoutError,
        match="DEPENDENCY_TIMEOUT",
    ):
        DateOfBirthRecognizer().analyze(
            "생년월일 2004-01-02",
            [ENTITY],
        )


def test_unexpected_runtime_failure_is_not_safe_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_boundary(callback):
        def wrapped(*args, **kwargs):
            raise RuntimeError("TEST_RUNTIME_FAILURE")

        return wrapped

    monkeypatch.setattr(
        dob_module,
        "protect_callable",
        failing_boundary,
    )

    with pytest.raises(
        RuntimeError,
        match="TEST_RUNTIME_FAILURE",
    ):
        DateOfBirthRecognizer().analyze(
            "생년월일 2004-01-02",
            [ENTITY],
        )
