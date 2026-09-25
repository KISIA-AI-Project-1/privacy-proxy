"""Application factory; frozen harnesses are references, never imports."""

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NoOpNlpEngine

from .registry import build_registry, validate_registry


def build_analyzer() -> AnalyzerEngine:
    registry = build_registry()
    analyzer = AnalyzerEngine(
        registry=registry,
        nlp_engine=NoOpNlpEngine(models=[{"lang_code": "ko", "model_name": ""}]),
        supported_languages=["ko"],
        default_score_threshold=0.0,
        log_decision_process=False,
    )
    validate_registry(analyzer.registry)
    return analyzer
