"""R7 ADDRESS v1: self-contained full-address structural rules, raw offsets only."""

from typing import Any, cast

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult

from privacy_proxy.contracts.detection import validate_span

from .timeout_guard import protect_callable

_HORIZONTAL = r"[ \t]+"
_SIDO = r"[가-힣]+(?:특별자치도|특별자치시|특별시|광역시|도)"
# A metropolitan/provincial token must not masquerade as a local city anchor.
_LOCAL_ADMIN = rf"(?!(?:{_SIDO})(?={_HORIZONTAL}))[가-힣]+(?:시|군|구)"
_LOCALITY = r"[가-힣0-9]+(?:읍|면|동|리)"
_ROAD = r"[가-힣0-9]+(?:대로|로|길)"
_NUMBER = r"[1-9][0-9]*(?:-[1-9][0-9]*)?(?![0-9-])"
_ANCHOR = rf"(?:{_SIDO}{_HORIZONTAL})?{_LOCAL_ADMIN}(?:{_HORIZONTAL}{_LOCAL_ADMIN})*"
_NORMAL_CORE = (
    rf"{_ANCHOR}{_HORIZONTAL}"
    rf"(?:(?:{_LOCALITY}{_HORIZONTAL})*{_ROAD}|"
    rf"{_LOCALITY}(?:{_HORIZONTAL}{_LOCALITY})*){_HORIZONTAL}{_NUMBER}"
)
_SEJONG_CORE = rf"세종특별자치시{_HORIZONTAL}{_ROAD}{_HORIZONTAL}{_NUMBER}"
# Punctuation cannot be part of a detail token; suffix endings stay outside it.
_DETAIL = r"(?:[^\W_]+빌딩|[1-9][0-9]*(?:동|층|호))"
_ADDRESS = regex.compile(rf"(?<!\w)(?:{_SEJONG_CORE}|{_NORMAL_CORE})(?:{_HORIZONTAL}{_DETAIL})*")
_REGEX_TIMEOUT = 0.1


class AddressRecognizer(EntityRecognizer):
    """Emit one longest surface per core; no model, normalization or replacement."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        super().__init__(
            supported_entities=["ADDRESS"],
            supported_language=supported_language,
            name="AddressRecognizer",
        )

    def load(self) -> None:
        """No resources to load."""

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: Any = None
    ) -> list[RecognizerResult]:
        if "ADDRESS" not in entities:
            return []
        return cast(list[RecognizerResult], protect_callable(self._analyze)(text))

    def _analyze(self, text: str) -> list[RecognizerResult]:
        results = []
        # Greedy detail extension and nonoverlapping iteration avoid emitting
        # the shorter core or an interior administrative suffix as duplicates.
        for match in _ADDRESS.finditer(text, timeout=_REGEX_TIMEOUT):
            start, end = match.span()
            validate_span(text, start, end)
            results.append(
                RecognizerResult(
                    entity_type="ADDRESS",
                    start=start,
                    end=end,
                    score=0.5,  # Internal metadata, never common confidence/tier evidence.
                    recognition_metadata={
                        RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                        RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                    },
                )
            )
        return results
