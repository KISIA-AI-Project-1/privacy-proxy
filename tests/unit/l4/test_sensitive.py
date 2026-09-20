"""민감정보 앵커 인식기 테스트. 픽스처는 전부 가상값이다.

형식 정규식이 없다 — 앵커 단어의 등장 자체가 탐지 대상이라 경계 확정이나
문맥 판별 없이 그대로 매치된다.
"""

from l4.sensitive import (
    find_sensitive_family,
    find_sensitive_financial,
    find_sensitive_health,
    find_sensitive_religion,
)

from privacy_proxy.schemas import DetectedPII, DetectionTier


def _types(results: list[DetectedPII]) -> list[str]:
    return [r.entity_type for r in results]


def test_건강_앵커_매치() -> None:
    results = find_sensitive_health("아이가 아토피라 이 제품은 못 쓰겠어요")

    assert _types(results) == ["SENSITIVE_HEALTH"]
    assert results[0].original_value == "아토피"


def test_건강_앵커는_오탐_후보여도_그대로_매치된다() -> None:
    """ "아토피 연고 재구매" — 경계 확정을 안 해서 걸러지지 않는다.

    설계대로다: confidence가 낮고(0.4) tier도 가장 낮은 CANDIDATE라
    최종 판단은 L5로 넘어간다.
    """
    results = find_sensitive_health("아토피 연고 재구매하려는데")

    assert _types(results) == ["SENSITIVE_HEALTH"]
    assert results[0].confidence == 0.4
    assert results[0].tier is DetectionTier.CANDIDATE


def test_종교_앵커는_부분_문자열로도_매치된다() -> None:
    """앵커 목록엔 "종교"만 있지만 "종교상"의 일부로도 잡힌다(str.find 특성)."""
    results = find_sensitive_religion("종교상 이유로 이 제품은 못 먹어요")

    assert _types(results) == ["SENSITIVE_RELIGION"]
    assert results[0].original_value == "종교"
    assert results[0].start_idx == 0
    assert results[0].end_idx == 2


def test_재정_앵커_매치() -> None:
    results = find_sensitive_financial("파산 신청했는데 환불 가능할까요")

    assert _types(results) == ["SENSITIVE_FINANCIAL"]
    assert results[0].original_value == "파산"


def test_가족_앵커_매치() -> None:
    """ "아이가"/"남편이"류는 일상적 구매 후기에도 흔해 오탐 위험이 크다 —
    시드 그대로 반영했으므로 지금은 그대로 매치되는 게 맞는 동작이다.
    """
    results = find_sensitive_family("남편이 생일 선물로 사줬어요")

    assert _types(results) == ["SENSITIVE_FAMILY"]
    assert results[0].original_value == "남편이"


def test_카테고리는_서로_배타적이지_않다() -> None:
    """ "아이가"(가족)와 "아토피"(건강)가 같은 문장에서 각자 독립적으로 매치."""
    text = "아이가 아토피라 이 제품은 못 쓰겠어요"

    assert _types(find_sensitive_health(text)) == ["SENSITIVE_HEALTH"]
    assert _types(find_sensitive_family(text)) == ["SENSITIVE_FAMILY"]


def test_앵커_없으면_빈_리스트() -> None:
    text = "배송이 언제 오나요"

    assert find_sensitive_health(text) == []
    assert find_sensitive_religion(text) == []
    assert find_sensitive_family(text) == []
    assert find_sensitive_financial(text) == []


def test_같은_앵커가_여러_번_나오면_전부_매치() -> None:
    results = find_sensitive_financial("대출 갚느라 힘든데 대출 하나 더 받았어요")

    assert len(results) == 2
    assert [r.start_idx for r in results] == [0, 11]


def test_normalized는_표면형과_같고_segment_id도_전달된다() -> None:
    results = find_sensitive_health("천식이 있어서 향 없는 제품 찾아요", segment_id="seg-3")

    assert len(results) == 1
    pii = results[0]
    assert pii.normalized == pii.original_value == "천식"
    assert pii.segment_id == "seg-3"
    assert pii.source == "L4_SENSITIVE_HEALTH"
