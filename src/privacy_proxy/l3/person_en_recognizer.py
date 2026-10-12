"""Isolated English PERSON model evidence with raw-coordinate refinement."""

from __future__ import annotations

import unicodedata
from threading import Lock
from typing import Any, cast

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from privacy_proxy.contracts.detection import validate_span

_MODEL_NAME = "en_core_web_lg"
_POSTPOSITIONS = tuple(
    sorted(
        (
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "와",
            "과",
            "의",
            "에게",
            "께",
            "도",
            "만",
            "로",
            "으로",
            "에서",
            "부터",
            "까지",
        ),
        key=len,
        reverse=True,
    )
)
_ENGLISH_ANALYZER: AnalyzerEngine | None = None
_ENGLISH_ANALYZER_LOCK = Lock()


class PersonEnDependencyError(RuntimeError):
    """Reason codes only; dependency exception text may contain sensitive data."""


def _build_english_analyzer() -> AnalyzerEngine:
    import spacy

    # Direct loading fails if absent; SpacyNlpEngine.load() may download models.
    model = spacy.load(_MODEL_NAME)
    if (
        model.lang != "en"
        or model.meta.get("name") != "core_web_lg"
        or not model.has_pipe("ner")
        or "PERSON" not in getattr(model.get_pipe("ner"), "labels", ())
    ):
        raise PersonEnDependencyError("PERSON_EN_MODEL_CAPABILITY_MISSING")
    engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": _MODEL_NAME}])
    cast(Any, engine).nlp = {"en": model}
    return AnalyzerEngine(
        registry=RecognizerRegistry(
            recognizers=[SpacyRecognizer(supported_entities=["PERSON"], supported_language="en")],
            supported_languages=["en"],
        ),
        nlp_engine=engine,
        supported_languages=["en"],
        default_score_threshold=0.0,
        log_decision_process=False,
    )


def _get_english_analyzer() -> AnalyzerEngine:
    global _ENGLISH_ANALYZER
    # Share across recognizer/service instances, including concurrent first use.
    with _ENGLISH_ANALYZER_LOCK:
        if _ENGLISH_ANALYZER is None:
            try:
                analyzer = _build_english_analyzer()
            except Exception:
                raise PersonEnDependencyError("PERSON_EN_INITIALIZATION_FAILED") from None
            # Publish only a completely initialized capability.
            _ENGLISH_ANALYZER = analyzer
        return _ENGLISH_ANALYZER


class PersonEnRecognizer(EntityRecognizer):
    """Expose only PERSON_EN through the existing Korean outer analyzer."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        super().__init__(
            supported_entities=["PERSON_EN"],
            supported_language=supported_language,
            name="PersonEnRecognizer",
        )

    def load(self) -> None:
        """Presidio calls this in __init__; defer all model loading to analysis."""

    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts: Any = None,
    ) -> list[RecognizerResult]:
        if "PERSON_EN" not in entities:
            return []
        analyzer = _get_english_analyzer()
        try:
            upstream = analyzer.analyze(
                text=text,
                language="en",
                entities=["PERSON"],
                score_threshold=0.0,
                return_decision_process=False,
            )
        except Exception:
            raise PersonEnDependencyError("PERSON_EN_ANALYSIS_FAILED") from None

        results: list[RecognizerResult] = []
        for candidate in upstream:
            if candidate.entity_type != "PERSON":
                continue
            start, end = candidate.start, candidate.end
            validate_span(text, start, end)
            surface = text[start:end]
            for suffix in _POSTPOSITIONS:
                if surface.endswith(suffix):
                    end -= len(suffix)
                    break
            if text[start:end].endswith(("'s", "\u2019s")):
                end -= 2
            surface = text[start:end]
            if end <= start or not surface.strip():
                continue
            if any("HANGUL" in unicodedata.name(char, "") for char in surface):
                continue
            validate_span(text, start, end)
            results.append(
                RecognizerResult(
                    entity_type="PERSON_EN",
                    start=start,
                    end=end,
                    # Internal Presidio score only; the adapter keeps confidence null.
                    score=candidate.score,
                    recognition_metadata={
                        RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                        RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                    },
                )
            )
        return results
