"""DATE_OF_BIRTH v0.1: bounded birth-date extraction with local evidence.

Supported surfaces are YYYY-MM-DD, YYYYMMDD, and YYYY년 M월 D일.
A date is emitted only when approved birth semantics are locally present:
a bounded 생년월일/생일 prefix relation or the Korean-native immediate
suffix relation `일생`.

Raw coordinates are preserved. Calendar validity and future-date rejection
are semantic validation. No normalization, inference, logging, or shared
mutable request state is performed here.
"""

from datetime import UTC, date, datetime
from typing import Any, cast

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult

from .timeout_guard import protect_callable

MAX_ANCHOR_DISTANCE = 15
_REGEX_TIMEOUT = 0.1
_MAX_ANCHOR_LENGTH = len("생년월일")

_CLAUSE = regex.compile(r"[^.!?\r\n]+")
_ANCHOR = regex.compile(r"(?<!\w)(?:생년월일|생일)")

_DATE_CANDIDATE = regex.compile(
    r"(?P<iso>"
    r"(?<![0-9])"
    r"(?P<iso_year>[0-9]{4})-"
    r"(?P<iso_month>[0-9]{2})-"
    r"(?P<iso_day>[0-9]{2})"
    r"(?![0-9])"
    r")"
    r"|"
    r"(?P<compact>"
    r"(?<![0-9])"
    r"(?P<compact_year>[0-9]{4})"
    r"(?P<compact_month>[0-9]{2})"
    r"(?P<compact_day>[0-9]{2})"
    r"(?![0-9])"
    r")"
    r"|"
    r"(?P<korean>"
    r"(?<![0-9])"
    r"(?P<korean_year>[0-9]{4})년[ \t]+"
    r"(?P<korean_month>[0-9]{1,2})월[ \t]+"
    r"(?P<korean_day>[0-9]{1,2})일"
    r")"
)


def _utc_today() -> date:
    """Return the current UTC calendar date through a replaceable test seam."""
    return datetime.now(UTC).date()


def _parts(candidate: Any) -> tuple[int, int, int]:
    """Return Gregorian components from one supported raw date surface."""
    if candidate.group("iso") is not None:
        return (
            int(candidate.group("iso_year")),
            int(candidate.group("iso_month")),
            int(candidate.group("iso_day")),
        )

    if candidate.group("compact") is not None:
        return (
            int(candidate.group("compact_year")),
            int(candidate.group("compact_month")),
            int(candidate.group("compact_day")),
        )

    return (
        int(candidate.group("korean_year")),
        int(candidate.group("korean_month")),
        int(candidate.group("korean_day")),
    )


def _calendar_date(candidate: Any) -> date | None:
    """Reject structurally matched but invalid Gregorian dates."""
    year, month, day = _parts(candidate)

    try:
        return date(year, month, day)
    except ValueError:
        return None


def _valid_prefix_gap(gap: str) -> bool:
    """Validate the frozen anchor -> date relation without normalization."""
    if not 1 <= len(gap) <= MAX_ANCHOR_DISTANCE:
        return False

    index = 0
    particle = False
    delimiter = False

    if index < len(gap) and gap[index] in "은는이":
        particle = True
        index += 1

    while index < len(gap) and gap[index] in " \t":
        index += 1

    if index < len(gap) and gap[index] in ":=":
        delimiter = True
        index += 1

    while index < len(gap) and gap[index] in " \t":
        index += 1

    if index != len(gap):
        return False

    # With neither a particle nor delimiter, a real horizontal gap is required.
    if not particle and not delimiter:
        return all(character in " \t" for character in gap)

    return True


def _has_prefix_evidence(
    text: str,
    surface_start: int,
    clause_start: int,
) -> bool:
    """Accept only an approved bounded birth anchor relation."""
    window_start = max(
        clause_start,
        surface_start - MAX_ANCHOR_DISTANCE - _MAX_ANCHOR_LENGTH,
    )

    for anchor in _ANCHOR.finditer(
        text,
        window_start,
        surface_start,
        timeout=_REGEX_TIMEOUT,
    ):
        gap = text[anchor.end() : surface_start]

        if _valid_prefix_gap(gap):
            return True

    return False


def _has_suffix_evidence(
    text: str,
    candidate: Any,
) -> bool:
    """Only Korean-native full dates support the immediate `생` relation."""
    if candidate.group("korean") is None:
        return False

    end = candidate.end()

    return end < len(text) and text[end] == "생"


class DateOfBirthRecognizer(EntityRecognizer):
    """Emit DATE_OF_BIRTH only after local birth semantics validate."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        super().__init__(
            supported_entities=["DATE_OF_BIRTH"],
            supported_language=supported_language,
            name="DateOfBirthRecognizer",
        )

    def load(self) -> None:
        """Compiled immutable patterns require no model initialization."""

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: Any = None,
    ) -> list[RecognizerResult]:
        if "DATE_OF_BIRTH" not in entities:
            return []

        return cast(
            list[RecognizerResult],
            protect_callable(self._analyze)(text),
        )

    def _analyze(self, text: str) -> list[RecognizerResult]:
        results: list[RecognizerResult] = []
        seen: set[tuple[str, int, int]] = set()

        today = _utc_today()

        for clause in _CLAUSE.finditer(
            text,
            timeout=_REGEX_TIMEOUT,
        ):
            clause_start, clause_end = clause.span()

            for candidate in _DATE_CANDIDATE.finditer(
                text,
                clause_start,
                clause_end,
                timeout=_REGEX_TIMEOUT,
            ):
                candidate_date = _calendar_date(candidate)

                if candidate_date is None:
                    continue

                if candidate_date > today:
                    continue

                start, end = cast(tuple[int, int], candidate.span())

                prefix_evidence = _has_prefix_evidence(
                    text,
                    start,
                    clause_start,
                )

                suffix_evidence = _has_suffix_evidence(
                    text,
                    candidate,
                )

                if not prefix_evidence and not suffix_evidence:
                    continue

                key = ("DATE_OF_BIRTH", start, end)

                if key in seen:
                    continue

                seen.add(key)

                results.append(
                    RecognizerResult(
                        entity_type="DATE_OF_BIRTH",
                        start=start,
                        end=end,
                        score=0.5,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )

        return results
