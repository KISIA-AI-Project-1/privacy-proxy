"""Project-local Korean driver's-license boundary hardening."""

from copy import deepcopy

from presidio_analyzer import Pattern
from presidio_analyzer.predefined_recognizers import (
    KrDriverLicenseRecognizer as PresidioKrDriverLicenseRecognizer,
)


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
