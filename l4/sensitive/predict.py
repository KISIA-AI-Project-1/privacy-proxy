"""1단계 앵커 후보 → 2단계 KoELECTRA 이진분류로 재판정 — 런타임 추론 경로.

CLAUDE.md "2단계 설계"(확정)를 그대로 따른다: 모델은 문장 전체를 스캔하지
않는다 — 1단계(``recognizers.py``)가 앵커로 좁힌 자리 주변 윈도우만 본다.
확률 ≥ threshold(POSITIVE)면 emit, 아니면 버린다. tier는 CANDIDATE로 유지하고
confidence만 모델 확률로 바꾼다 — 최종 판단은 여전히 L5 몫이다.

``load_model``은 ``l4/ner/predict.py``와 같은 패턴(경로를 인자로 받고
하드코딩 안 함, 존재 확인은 호출부에서)을 따른다. ``l4/sensitive/train.py``는
일부러 import하지 않는다 — vocab은 같지만 ``datasets``/``Trainer`` 등 학습
전용 의존성까지 실시간 추론 경로에 끌려온다(CI가 이미 겪은
``--extra training`` 문제와 같은 종류). POSITIVE 라벨 인덱스는 체크포인트
자체의 ``model.config.label2id`` 에서 읽는다 — ``l4/ner/predict.py`` 가
``model.config.id2label`` 을 쓰는 것과 동일한 이유(재학습·재저장돼도 안전).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from l4.sensitive.context import window_text
from l4.sensitive.recognizers import (
    find_sensitive_family,
    find_sensitive_financial,
    find_sensitive_health,
    find_sensitive_religion,
)
from privacy_proxy.schemas import DetectedPII

# ponytail: 앵커 좌우 문자 수. max_length=64 토큰 예산 안에 들어오도록 넉넉히
# 잡은 임의값 — 최종 길이 제한은 토크나이저 truncation에 맡긴다. 앵커가 긴
# 문단 중간에 있을 때 이 값이 적절한지는 W7 실측 대상(train.py 모듈독스트링
# 의 "파이프라인 배선 시 별도 확정" 항목과 동일 이슈).
WINDOW_CHARS = 60

# TODO(W7): 합성 평가셋(adversarial.jsonl) 실측 후 조정. CLAUDE.md "2단계 설계" 참고.
THRESHOLD = 0.7

# adversarial.jsonl 실측(2026-09-23, CLAUDE.md "adversarial.jsonl 작성 + 실측 완료"
# 참고) 결과 2단계 모델이 BoW 베이스라인 대비 유의미한 이점을 보인 카테고리만
# 재판정을 적용한다. RELIGION(BoW와 동률)·FINANCIAL(BoW보다 낮음 — 금액 어휘
# 지름길 의심)은 표면형 다양화 등 데이터 재작업 전까지 1단계 결과를 그대로 emit.
REFINED_CATEGORIES = frozenset({"SENSITIVE_FAMILY", "SENSITIVE_HEALTH"})


def load_model(model_dir: str | Path) -> tuple[Any, Any]:
    """저장된 run의 모델·토크나이저를 불러온다."""
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    return model, tokenizer


def build_windows(
    candidates: list[DetectedPII], text: str, window_chars: int = WINDOW_CHARS
) -> list[str]:
    """앵커 후보 각각의 주변 텍스트를 뽑는다. 모델 호출 없는 순수 함수."""
    return [window_text(text, c.start_idx, c.end_idx, window_chars) for c in candidates]


def classify_windows(
    windows: list[str], model: Any, tokenizer: Any, max_length: int = 64
) -> list[float]:
    """윈도우 텍스트 리스트 → POSITIVE 확률 리스트. 배치 추론 한 번."""
    if not windows:
        return []
    encoded = tokenizer(
        windows, truncation=True, max_length=max_length, padding=True, return_tensors="pt"
    )
    model.eval()
    with torch.inference_mode():
        logits = model(**encoded).logits
    positive_id = model.config.label2id["POSITIVE"]
    probs = torch.softmax(logits, dim=-1)[:, positive_id]
    # torch 타입 스텁이 부실해서 tolist()가 Any로 잡힌다(l4/recognizers/recognizers.py의
    # phonenumbers.is_valid_number와 같은 패턴) — 명시적 로컬 어노테이션으로 고정.
    result: list[float] = probs.tolist()
    return result


def apply_threshold(
    candidates: list[DetectedPII], probs: list[float], threshold: float = THRESHOLD
) -> list[DetectedPII]:
    """확률 ≥ threshold인 후보만 confidence를 모델 확률로 바꿔 emit. 모델 호출 없는 순수 함수."""
    if len(candidates) != len(probs):
        raise ValueError("candidates/probs 길이가 어긋난다")
    return [
        candidate.model_copy(update={"confidence": prob})
        for candidate, prob in zip(candidates, probs, strict=True)
        if prob >= threshold
    ]


def refine_candidates(
    candidates: list[DetectedPII],
    text: str,
    model: Any,
    tokenizer: Any,
    threshold: float = THRESHOLD,
    window_chars: int = WINDOW_CHARS,
    max_length: int = 64,
) -> list[DetectedPII]:
    """1단계 후보 → 윈도우 생성 → 배치 추론 → threshold 적용까지의 결합 로직."""
    windows = build_windows(candidates, text, window_chars)
    probs = classify_windows(windows, model, tokenizer, max_length)
    return apply_threshold(candidates, probs, threshold)


def find_sensitive(
    text: str,
    model: Any,
    tokenizer: Any,
    segment_id: str = "seg-1",
    threshold: float = THRESHOLD,
) -> list[DetectedPII]:
    """1단계 4종 전부 → REFINED_CATEGORIES만 2단계 재판정, 나머지는 1단계 결과 그대로.

    문장당 배치 추론 한 번(재판정 대상 카테고리만 윈도우에 태움 — 비재판정
    카테고리는 애초에 모델 입력에 안 들어가 배치 크기도 줄어든다).
    """
    candidates = [
        *find_sensitive_health(text, segment_id),
        *find_sensitive_religion(text, segment_id),
        *find_sensitive_family(text, segment_id),
        *find_sensitive_financial(text, segment_id),
    ]
    refined = [c for c in candidates if c.entity_type in REFINED_CATEGORIES]
    passthrough = [c for c in candidates if c.entity_type not in REFINED_CATEGORIES]
    return passthrough + refine_candidates(refined, text, model, tokenizer, threshold)
