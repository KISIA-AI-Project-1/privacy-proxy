"""로컬 L4 NER 모델 결과를 공통 탐지 형식으로 변환한다."""

from pathlib import Path
from threading import Lock
from typing import Any

from privacy_proxy.config import get_settings
from privacy_proxy.schemas import DetectedPII, DetectionTier

_runtime: tuple[Any, Any, Any] | None = None
_runtime_lock = Lock()


def detect_l4_ner(
    text: str,
    *,
    segment_id: str,
) -> list[DetectedPII]:
    """세그먼트 기준 좌표를 반환한다. 전체 원문 변환은 파이프라인에서 한다."""
    global _runtime

    settings = get_settings()
    if not settings.l4_ner_enabled:
        return []

    model_path = settings.l4_ner_model_path.strip()
    if not model_path or not Path(model_path).is_dir():
        raise RuntimeError("L4_NER_MODEL_PATH_INVALID")

    # 비활성화 상태에서는 torch와 transformers를 불러오지 않는다.
    from l4.ner.predict import load_model, predict_spans

    with _runtime_lock:
        if _runtime is None:
            model, tokenizer, labels = load_model(model_path)
            model.to("cpu")
            model.eval()
            _runtime = (model, tokenizer, labels)

        model, tokenizer, labels = _runtime
        spans = predict_spans(text, model, tokenizer, labels)

    results: list[DetectedPII] = []
    for span in spans:
        if span.entity_type not in {"PERSON_KO", "LOCATION_INFORMAL"}:
            raise ValueError("L4_NER_UNSUPPORTED_ENTITY")

        if not 0 <= span.start < span.end <= len(text):
            raise ValueError("L4_NER_INVALID_SPAN")

        original = text[span.start : span.end]
        if original != span.text:
            raise ValueError("L4_NER_SPAN_TEXT_MISMATCH")

        results.append(
            DetectedPII(
                segment_id=segment_id,
                start_idx=span.start,
                end_idx=span.end,
                entity_type=span.entity_type,
                original_value=original,
                normalized=original,
                confidence=None,
                tier=DetectionTier.MODEL,
                source="L4_KLUE_NER",
            )
        )

    return results
