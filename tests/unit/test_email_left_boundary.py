import pytest

from privacy_proxy.l3.registry import build_registry, validate_registry

EMAIL = "audit+tag@example.com"

KOREAN_EMAIL_LABEL = "\uc774\uba54\uc77c"
KOREAN_MAIL_LABEL = "\uba54\uc77c"
KOREAN_SUFFIX = "\uc785\ub2c8\ub2e4"


def configured_email():
    registry = build_registry()
    return validate_registry(registry)["EMAIL_ADDRESS"]


def assert_exact_email(producer, raw: str, expected: str, expected_start: int) -> None:
    results = producer.analyze(
        text=raw,
        entities=["EMAIL_ADDRESS"],
    )

    assert len(results) == 1

    result = results[0]
    expected_end = expected_start + len(expected)

    assert result.start == expected_start
    assert result.end == expected_end
    assert raw[result.start : result.end] == expected


@pytest.mark.parametrize(
    "label",
    (
        KOREAN_EMAIL_LABEL,
        KOREAN_MAIL_LABEL,
    ),
)
def test_known_korean_email_label_is_not_part_of_email_span(label: str) -> None:
    producer = configured_email()

    raw = label + EMAIL

    assert_exact_email(
        producer,
        raw,
        EMAIL,
        len(label),
    )


@pytest.mark.parametrize(
    "label",
    (
        KOREAN_EMAIL_LABEL,
        KOREAN_MAIL_LABEL,
    ),
)
def test_known_label_and_korean_suffix_keep_exact_email_span(label: str) -> None:
    producer = configured_email()

    raw = label + EMAIL + KOREAN_SUFFIX

    assert_exact_email(
        producer,
        raw,
        EMAIL,
        len(label),
    )


def test_existing_right_korean_suffix_behavior_is_preserved() -> None:
    producer = configured_email()

    raw = EMAIL + KOREAN_SUFFIX

    assert_exact_email(
        producer,
        raw,
        EMAIL,
        0,
    )


def test_delimited_label_remains_exact() -> None:
    producer = configured_email()

    raw = KOREAN_EMAIL_LABEL + ":" + EMAIL

    assert_exact_email(
        producer,
        raw,
        EMAIL,
        len(KOREAN_EMAIL_LABEL) + 1,
    )


def test_nonlabel_unicode_localpart_is_not_blindly_trimmed() -> None:
    producer = configured_email()

    expected = "\ud64d\uae38\ub3d9@example.com"

    assert_exact_email(
        producer,
        expected,
        expected,
        0,
    )


def test_label_prefix_collision_is_not_blindly_trimmed() -> None:
    producer = configured_email()

    expected = "\uba54\uc77c\ud568@example.com"

    assert_exact_email(
        producer,
        expected,
        expected,
        0,
    )


def test_unicode_domain_behavior_is_preserved() -> None:
    producer = configured_email()

    expected = "audit@\uc608\uc2dc.com"

    assert_exact_email(
        producer,
        expected,
        expected,
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
def test_embedded_label_text_inside_unicode_localpart_is_preserved(
    expected: str,
) -> None:
    producer = configured_email()

    assert_exact_email(
        producer,
        expected,
        expected,
        0,
    )
