"""Single complete raw_prompt only; no segment-local/global conversion."""

from privacy_proxy.schemas import DetectedPII

from .analyzer_factory import build_analyzer
from .detection_adapter import adapt_result
from .registry import SUPPORTED_ENTITIES, validate_registry
from .timeout_guard import L3DependencyTimeoutError, protect_patterns


class UnsupportedCapabilityError(ValueError):
    """Requested language/entity is not implemented."""


class L3RuntimeError(RuntimeError):
    """Runtime failure, never a successful empty detection list."""


class L3AnalyzerService:
    def __init__(self) -> None:
        try:
            self._analyzer = build_analyzer()
            protect_patterns(self._analyzer.registry)
        except Exception:
            raise L3RuntimeError("ANALYZER_INITIALIZATION_FAILED") from None

    def analyze(
        self,
        raw_prompt: str,
        segment_id: str,
        language: str = "ko",
        entities: list[str] | tuple[str, ...] | None = None,
    ) -> list[DetectedPII]:
        if not isinstance(raw_prompt, str):
            raise ValueError("RAW_PROMPT_TYPE")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise ValueError("SEGMENT_ID_REQUIRED")
        if language != "ko":
            raise UnsupportedCapabilityError("UNSUPPORTED_LANGUAGE")
        if entities is None:
            requested = list(SUPPORTED_ENTITIES)
        else:
            if not isinstance(entities, (list, tuple)) or any(
                not isinstance(entity, str) for entity in entities
            ):
                raise UnsupportedCapabilityError("ENTITIES_TYPE")
            if any(entity not in SUPPORTED_ENTITIES for entity in entities):
                raise UnsupportedCapabilityError("UNSUPPORTED_ENTITY")
            requested = list(dict.fromkeys(entities))
        # Validate even if an explicit empty entity list was requested.
        validate_registry(self._analyzer.registry)
        if self._analyzer.supported_languages != ["ko"] or self._analyzer.log_decision_process:
            raise L3RuntimeError("ANALYZER_CONFIGURATION_CHANGED")
        if not requested:
            return []
        try:
            results = self._analyzer.analyze(
                text=raw_prompt,
                language=language,
                entities=requested,
                score_threshold=0.0,
                return_decision_process=False,
            )
            if any(result.entity_type not in requested for result in results):
                raise L3RuntimeError("UNREQUESTED_RESULT")
            return [
                adapt_result(result, raw_prompt, segment_id, self._analyzer.registry)
                for result in results
            ]
        except L3DependencyTimeoutError:
            raise
        except Exception:
            # Suppress sensitive dependency exception text, not the failure.
            raise L3RuntimeError("L3_ANALYSIS_OR_ADAPTATION_FAILED") from None
