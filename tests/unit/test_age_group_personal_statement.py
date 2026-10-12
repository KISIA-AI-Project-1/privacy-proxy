import pytest

from privacy_proxy.l3.registry import build_registry, validate_registry


def configured_age_group():
    registry = build_registry()
    return validate_registry(registry)["AGE_GROUP"]


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
def test_bare_personal_age_group_is_detected(
    raw: str,
    expected: str,
) -> None:
    producer = configured_age_group()

    results = producer.analyze(
        text=raw,
        entities=["AGE_GROUP"],
    )

    assert len(results) == 1

    result = results[0]

    assert result.start == 0
    assert result.end == len(expected)
    assert raw[result.start : result.end] == expected


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
def test_bare_age_group_does_not_broaden_nonpersonal_context(
    raw: str,
) -> None:
    producer = configured_age_group()

    results = producer.analyze(
        text=raw,
        entities=["AGE_GROUP"],
    )

    assert results == []
