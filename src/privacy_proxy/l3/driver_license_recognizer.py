"""Project-local Korean driver's-license boundary hardening."""

from copy import deepcopy

from presidio_analyzer import Pattern, RecognizerResult
from presidio_analyzer.nlp_engine import NlpArtifacts
from presidio_analyzer.predefined_recognizers import (
    KrDriverLicenseRecognizer as PresidioKrDriverLicenseRecognizer,
)

_COMPACT_LICENSE_CONTEXT = (
    "운전면허번호",
    "운전면허",
    "면허번호",
)

_COMPACT_COMPETING_CONTEXT = (
    "송장번호",
    "운송장번호",
    "택배번호",
    "주문번호",
    "고객번호",
)

_COMPACT_CONTEXT_WINDOW = 24
_COMPACT_CONTEXT_MAX_GAP = 6

_COMPACT_CONTEXT_GAP_CHARS = frozenset(" \t\r\n:\N{FULLWIDTH COLON}=,.;!?()[]{}<>은는이가의")


def _is_local_context_gap(gap: str) -> bool:
    """Return whether only a short separator gap exists."""
    return len(gap) <= _COMPACT_CONTEXT_MAX_GAP and all(
        char in _COMPACT_CONTEXT_GAP_CHARS for char in gap
    )


def _nearest_compact_context_distance(
    text: str,
    start: int,
    end: int,
    anchors: tuple[str, ...],
) -> int | None:
    """Return the nearest directly associated local anchor distance."""
    left = text[max(0, start - _COMPACT_CONTEXT_WINDOW) : start]
    right = text[end : end + _COMPACT_CONTEXT_WINDOW]

    nearest: int | None = None

    for anchor in anchors:
        left_pos = left.rfind(anchor)

        if left_pos != -1:
            gap = left[left_pos + len(anchor) :]

            if _is_local_context_gap(gap):
                distance = len(gap)

                if nearest is None or distance < nearest:
                    nearest = distance

        right_pos = right.find(anchor)

        if right_pos != -1:
            gap = right[:right_pos]

            if _is_local_context_gap(gap):
                distance = len(gap)

                if nearest is None or distance < nearest:
                    nearest = distance

    return nearest


class KrDriverLicenseRecognizer(PresidioKrDriverLicenseRecognizer):
    """Reject license-shaped substrings embedded in ASCII identifiers."""

    # Presidio recognizers expose canonical patterns at class scope.
    PATTERNS: list[Pattern] = [  # noqa: RUF012
        Pattern(
            "Driver License (very weak)",
            (
                r"(?<![A-Za-z0-9])"
                r"(\d{2})[- ]?"
                r"(\d{2})[- ]?"
                r"(\d{6})[- ]?"
                r"(\d{2})"
                r"(?![A-Za-z0-9])"
            ),
            0.05,
        )
    ]

    def __init__(
        self,
        patterns: list[Pattern] | None = None,
        context: list[str] | None = None,
        supported_language: str = "ko",
        supported_entity: str = "KR_DRIVER_LICENSE",
        replacement_pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        instance_patterns = patterns if patterns else deepcopy(self.PATTERNS)

        super().__init__(
            patterns=instance_patterns,
            context=context,
            supported_language=supported_language,
            supported_entity=supported_entity,
            replacement_pairs=replacement_pairs,
        )

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: NlpArtifacts | None = None,
        regex_flags: int | None = None,
    ) -> list[RecognizerResult]:
        """Reject compact licenses only when a closer competing anchor owns the value."""
        results = super().analyze(
            text=text,
            entities=entities,
            nlp_artifacts=nlp_artifacts,
            regex_flags=regex_flags,
        )

        filtered: list[RecognizerResult] = []

        for result in results:
            original = text[result.start : result.end]

            is_compact = len(original) == 12 and original.isdigit()

            if is_compact:
                license_distance = _nearest_compact_context_distance(
                    text,
                    result.start,
                    result.end,
                    _COMPACT_LICENSE_CONTEXT,
                )

                competing_distance = _nearest_compact_context_distance(
                    text,
                    result.start,
                    result.end,
                    _COMPACT_COMPETING_CONTEXT,
                )

                if competing_distance is not None and (
                    license_distance is None or competing_distance < license_distance
                ):
                    continue

            filtered.append(result)

        return filtered
