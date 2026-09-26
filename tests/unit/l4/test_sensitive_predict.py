"""2단계 결합 로직 테스트 — 실제 체크포인트 로딩 없이 검증한다.

``build_windows``/``apply_threshold``는 모델 호출이 없는 순수 함수라 직접
검증한다. ``find_sensitive``(모델 호출부인 ``classify_windows``만 monkeypatch)로
1단계 4종 결합·배치 처리·threshold 배선을 검증한다. 실제 체크포인트로의
end-to-end 검증은 스코프 밖(CLAUDE.md 참고, 체크포인트 재검증 중).
"""

import pytest
from l4.sensitive import predict
from l4.sensitive.recognizers import find_sensitive_family, find_sensitive_health

from privacy_proxy.schemas import DetectedPII, DetectionTier


def test_build_windows는_span_주변_문자만_뽑는다() -> None:
    text = "고객님 아토피 때문에 문의드려요"
    candidates = find_sensitive_health(text)

    windows = predict.build_windows(candidates, text, window_chars=3)

    assert windows == ["객님 아토피 때문"]


def test_build_windows는_문자열_경계를_넘지_않는다() -> None:
    text = "아토피"
    candidates = find_sensitive_health(text)

    windows = predict.build_windows(candidates, text, window_chars=10)

    assert windows == ["아토피"]


def _pii(confidence: float = 0.4) -> DetectedPII:
    return DetectedPII(
        entity_type="SENSITIVE_HEALTH",
        original_value="아토피",
        start_idx=0,
        end_idx=3,
        confidence=confidence,
        tier=DetectionTier.CANDIDATE,
        source="L4_SENSITIVE_HEALTH",
    )


def test_apply_threshold는_임계값_이상만_통과시키고_confidence를_교체한다() -> None:
    candidates = [_pii(), _pii()]

    kept = predict.apply_threshold(candidates, [0.9, 0.5], threshold=0.7)

    assert len(kept) == 1
    assert kept[0].confidence == 0.9
    assert kept[0].tier is DetectionTier.CANDIDATE  # tier는 그대로 유지


def test_apply_threshold는_경계값_이상이면_통과() -> None:
    kept = predict.apply_threshold([_pii()], [0.7], threshold=0.7)

    assert len(kept) == 1


def test_apply_threshold는_길이_불일치면_에러() -> None:
    with pytest.raises(ValueError):
        predict.apply_threshold([_pii(), _pii()], [0.9])


def test_classify_windows는_빈_리스트면_모델_호출_없이_빈_리스트() -> None:
    assert predict.classify_windows([], model=None, tokenizer=None) == []


def test_find_sensitive는_앵커_없으면_모델_호출_없이_빈_리스트() -> None:
    """classify_windows를 monkeypatch하지 않는다 — 앵커가 없으면 windows가 빈
    리스트라 classify_windows의 가드(if not windows)가 실제 모델/토크나이저
    호출 전에 반환한다. model=None/tokenizer=None으로도 에러 없이 통과하는
    것 자체가 그 가드가 작동한다는 증거다.
    """
    result = predict.find_sensitive("배송이 언제 오나요", model=None, tokenizer=None)

    assert result == []


def test_find_sensitive는_4종_후보를_한_번에_배치_추론한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 문장에 HEALTH·FAMILY 앵커가 동시에 있으면 classify_windows가 한 번만 불린다."""
    text = "아이가 아토피라 이 제품은 못 쓰겠어요"
    calls: list[list[str]] = []

    def _fake_classify(
        windows: list[str], model: object, tokenizer: object, max_length: int = 64
    ) -> list[float]:
        calls.append(windows)
        return [0.9 for _ in windows]

    monkeypatch.setattr(predict, "classify_windows", _fake_classify)

    result = predict.find_sensitive(text, model=None, tokenizer=None)

    assert len(calls) == 1  # 배치 추론 한 번
    assert len(calls[0]) == 2  # HEALTH "아토피" + FAMILY "아이가"
    assert {r.entity_type for r in result} == {"SENSITIVE_HEALTH", "SENSITIVE_FAMILY"}
    assert all(r.confidence == 0.9 for r in result)


def test_find_sensitive는_threshold_미만은_제외한다(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "아토피 연고 재구매하려는데"

    monkeypatch.setattr(predict, "classify_windows", lambda *a, **k: [0.5])

    result = predict.find_sensitive(text, model=None, tokenizer=None, threshold=0.7)

    assert result == []


def test_find_sensitive는_REFINED_CATEGORIES_아니면_2단계_거치지_않고_그대로_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-09-27 기준 4종 전부 REFINED_CATEGORIES라 실제 카테고리로는 비REFINED
    케이스를 만들 수 없다 — 필터 로직 자체(특정 카테고리를 다시 뺄 수 있는 구조)는
    REFINED_CATEGORIES를 monkeypatch해서 검증한다. FINANCIAL을 임시로 밖으로
    빼면 classify_windows에 빈 윈도우만 전달되고(실제 모델 입력 없음), 1단계
    결과(confidence 0.4, tier CANDIDATE)가 그대로 나와야 한다.
    """
    monkeypatch.setattr(predict, "REFINED_CATEGORIES", frozenset({"SENSITIVE_HEALTH"}))
    text = "요즘 형편이 안 좋아서 결제가 늦었어요"
    calls: list[list[str]] = []

    def _fake_classify(
        windows: list[str], model: object, tokenizer: object, max_length: int = 64
    ) -> list[float]:
        calls.append(windows)
        return []

    monkeypatch.setattr(predict, "classify_windows", _fake_classify)

    result = predict.find_sensitive(text, model=None, tokenizer=None)

    assert calls == [[]]  # FINANCIAL 윈도우는 배치에 안 태워짐
    assert len(result) == 1
    assert result[0].entity_type == "SENSITIVE_FINANCIAL"
    assert result[0].confidence == 0.4
    assert result[0].tier is DetectionTier.CANDIDATE


def test_find_sensitive는_REFINED와_비REFINED_혼재시_REFINED만_배치_추론에_태운다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REFINED_CATEGORIES를 monkeypatch해 HEALTH(REFINED)+FINANCIAL(비REFINED)
    혼재를 재현한다 — classify_windows에는 HEALTH 윈도우만 들어가고, FINANCIAL은
    1단계 그대로 결과에 합류해야 한다.
    """
    monkeypatch.setattr(predict, "REFINED_CATEGORIES", frozenset({"SENSITIVE_HEALTH"}))
    text = "아토피 때문에 힘든데 형편이 어려워서 싼 걸로 주문했어요"
    calls: list[list[str]] = []

    def _fake_classify(
        windows: list[str], model: object, tokenizer: object, max_length: int = 64
    ) -> list[float]:
        calls.append(windows)
        return [0.9 for _ in windows]

    monkeypatch.setattr(predict, "classify_windows", _fake_classify)

    result = predict.find_sensitive(text, model=None, tokenizer=None)

    assert len(calls) == 1
    assert len(calls[0]) == 1  # HEALTH 앵커 1개만 배치에 들어감
    types = {r.entity_type for r in result}
    assert types == {"SENSITIVE_HEALTH", "SENSITIVE_FINANCIAL"}
    financial = next(r for r in result if r.entity_type == "SENSITIVE_FINANCIAL")
    assert financial.confidence == 0.4  # 1단계 고정값 그대로


def test_find_sensitive는_REFINED_다중후보와_비REFINED_혼재시_카테고리별로_정확히_매칭한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REFINED_CATEGORIES를 monkeypatch해 FAMILY(REFINED) 후보 2개 + FINANCIAL
    (비REFINED) 후보 1개 동시 등장을 재현한다. 배치 분리 후 재결합 과정에서
    원문값(original_value) 기준으로 정확한 카테고리·confidence에 매칭되는지
    확인 — 인덱스가 뒤섞이면 걸린다.
    """
    monkeypatch.setattr(predict, "REFINED_CATEGORIES", frozenset({"SENSITIVE_FAMILY"}))
    text = "아내가 좋아하고 부모님이 쓰실 물건인데 파산 신청 때문에 결제가 늦어요"

    def _fake_classify(
        windows: list[str], model: object, tokenizer: object, max_length: int = 64
    ) -> list[float]:
        assert len(windows) == 2  # FAMILY 2개만 배치에 들어감
        return [0.85, 0.75]  # 아내가, 부모님이 순

    monkeypatch.setattr(predict, "classify_windows", _fake_classify)

    result = predict.find_sensitive(text, model=None, tokenizer=None)

    by_value = {r.original_value: r for r in result}
    assert by_value["아내가"].entity_type == "SENSITIVE_FAMILY"
    assert by_value["아내가"].confidence == 0.85
    assert by_value["부모님이"].entity_type == "SENSITIVE_FAMILY"
    assert by_value["부모님이"].confidence == 0.75
    assert by_value["파산"].entity_type == "SENSITIVE_FINANCIAL"
    assert by_value["파산"].confidence == 0.4  # 1단계 고정값, 2단계 미적용
    assert by_value["파산"].tier is DetectionTier.CANDIDATE


def test_refine_candidates는_1단계_결과를_그대로_받아_재판정한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "남편이 생일 선물로 사줬어요"
    candidates = find_sensitive_family(text)

    monkeypatch.setattr(predict, "classify_windows", lambda *a, **k: [0.95])

    result = predict.refine_candidates(candidates, text, model=None, tokenizer=None)

    assert len(result) == 1
    assert result[0].original_value == "남편이"
    assert result[0].confidence == 0.95
