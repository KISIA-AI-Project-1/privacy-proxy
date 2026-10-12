"""Lazy LC model evidence with frozen v0.1.1 raw-coordinate refinement."""

from __future__ import annotations

import re
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from presidio_analyzer import EntityRecognizer, RecognizerResult

from privacy_proxy.contracts.detection import validate_span

from .timeout_guard import L3DependencyTimeoutError, protect_callable

if TYPE_CHECKING:
    from spacy.language import Language

_MODEL_NAME = "ko_core_news_lg"
_MODEL_VERSION = "3.8.0"
_SPACY_VERSION = "3.8.16"
_CONTROLLED_SUFFIXES = ("입니다", "이고", "에")
_ADMIN_ENDINGS = (
    ("SIDO", ("특별자치시", "특별자치도", "특별시", "광역시", "도")),
    ("SIGUNGU", ("시", "군", "구")),
    ("EUPMYEONDONG", ("읍", "면", "동")),
)
_ALL_ENDINGS = tuple(ending for _, endings in _ADMIN_ENDINGS for ending in endings)


class LocationDependencyError(RuntimeError):
    """Reason codes only; dependency exceptions may contain sensitive text."""


def _trim_suffix(token: str) -> str:
    for suffix in _CONTROLLED_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix):
            return token[: -len(suffix)]
    return token


def _classify(value: str) -> str | None:
    # Preserve frozen SIDO -> SIGUNGU -> EUPMYEONDONG priority.
    for classification, endings in _ADMIN_ENDINGS:
        if value.endswith(endings):
            return classification
    return None


def _has_concatenated_units(value: str) -> bool:
    """Frozen v0.1.1 full-token segmentation test, used only for rejection."""
    max_units = [-1] * (len(value) + 1)
    max_units[0] = 0
    for start in range(len(value)):
        if max_units[start] < 0:
            continue
        for end in range(start + 2, len(value) + 1):
            candidate = value[start:end]
            if any(
                candidate.endswith(ending) and len(candidate) > len(ending)
                for ending in _ALL_ENDINGS
            ):
                max_units[end] = max(max_units[end], max_units[start] + 1)
    return max_units[-1] >= 2


def _refine(surface: str, raw_start: int) -> list[tuple[int, int]]:
    """Refine one LC candidate atomically; never infer missing model spans."""
    spans: list[tuple[int, int]] = []
    for token in re.finditer(r"\S+", surface):
        value = _trim_suffix(token.group())
        if _has_concatenated_units(value) or _classify(value) is None:
            # R03/R04 reject the whole candidate, including earlier valid units.
            return []
        start = raw_start + token.start()
        spans.append((start, start + len(value)))
    return spans


class LocationRecognizer(EntityRecognizer):
    """Own only LOCATION; the model is required only for requested analysis."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        self._model: Language | None = None
        self._model_lock = Lock()
        super().__init__(
            supported_entities=["LOCATION"],
            supported_language=supported_language,
            name="LocationRecognizer",
        )

    def load(self) -> None:
        """Presidio calls this during construction; keep dependency loading lazy."""

    def _get_model(self) -> Language:
        with self._model_lock:
            if self._model is None:
                # Import/version/capability checks also remain request-local.
                import spacy
                from spacy.about import __version__ as spacy_version

                if spacy_version != _SPACY_VERSION:
                    raise LocationDependencyError("LOCATION_SPACY_VERSION_MISMATCH")
                try:
                    model = spacy.load(_MODEL_NAME)
                except TimeoutError:
                    raise
                except Exception:
                    raise LocationDependencyError("LOCATION_MODEL_LOAD_FAILED") from None
                if (
                    model.lang != "ko"
                    or model.meta.get("name") != "core_news_lg"
                    or model.meta.get("version") != _MODEL_VERSION
                ):
                    raise LocationDependencyError("LOCATION_MODEL_CONFIGURATION")
                if not model.has_pipe("ner") or "LC" not in getattr(
                    model.get_pipe("ner"), "labels", ()
                ):
                    raise LocationDependencyError("LOCATION_MODEL_LC_CAPABILITY_MISSING")
                # Cache only a successfully loaded and validated dependency.
                self._model = model
            return self._model

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: Any = None,
    ) -> list[RecognizerResult]:
        if "LOCATION" not in entities:
            return []
        try:
            return cast(list[RecognizerResult], protect_callable(self._analyze)(text))
        except (LocationDependencyError, L3DependencyTimeoutError):
            raise
        except Exception:
            raise LocationDependencyError("LOCATION_ANALYSIS_FAILED") from None

    def _analyze(self, text: str) -> list[RecognizerResult]:
        document = self._get_model()(text)
        if document.text != text:
            raise LocationDependencyError("LOCATION_MODEL_TEXT_MISMATCH")

        results: list[RecognizerResult] = []
        for candidate in document.ents:
            if candidate.label_ != "LC":
                continue
            start, end = candidate.start_char, candidate.end_char
            validate_span(text, start, end)
            surface = text[start:end]
            if candidate.text != surface:
                raise LocationDependencyError("LOCATION_MODEL_SPAN_MISMATCH")
            for unit_start, unit_end in _refine(surface, start):
                validate_span(text, unit_start, unit_end)
                results.append(
                    RecognizerResult(
                        entity_type="LOCATION",
                        start=unit_start,
                        end=unit_end,
                        # Required internal Presidio score, never common confidence.
                        score=0.5,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )
        return results
