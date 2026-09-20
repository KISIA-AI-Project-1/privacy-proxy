"""민감정보 앵커 인식기 테스트. 픽스처는 전부 가상값이다.

형식 정규식이 없다 — 앵커 단어의 등장 자체가 탐지 대상이라 경계 확정이나
문맥 판별 없이 그대로 매치된다.
"""

import pytest
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


# ── 앵커 조정 회귀: "사별" 추가, RELIGION "절" 단독 제거 ─────────────────────


def test_사별_앵커_매치() -> None:
    """FAMILY 시드에 "사별"이 없어서 사별 진술이 1단계에서 아예 안 잡히던 것."""
    results = find_sensitive_family("아내와 사별하고 혼자 지내는데 배송이 너무 늦어요")

    assert _types(results) == ["SENSITIVE_FAMILY"]
    assert results[0].original_value == "사별"


def test_돌아가신_앵커는_사별과_함께_유지된다() -> None:
    results = find_sensitive_family("어머니가 돌아가신 뒤로 혼자 지내요")

    assert [r.original_value for r in results] == ["돌아가신"]


@pytest.mark.parametrize("text", ["회사별 배송 현황 알려주세요", "고객사별 정산 내역 부탁드립니다"])
def test_사별은_합성어_안에서는_매치_안_된다(text: str) -> None:
    """ "회사별"·"고객사별"의 "사별"은 단어 시작이 아니라 걸리지 않는다(B2B CS 상투어)."""
    assert find_sensitive_family(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "환불 절차가 어떻게 되나요",
        "온도 조절이 안 돼요",
        "적절한 사이즈 추천해 주세요",
        "간절히 부탁드립니다",
        "주문 거절 사유가 뭔가요",
        "불친절해서 화가 납니다",
        "절대 못 참겠어요",
    ],
)
def test_절이_든_일상_단어는_종교_앵커가_아니다(text: str) -> None:
    """ "절"을 단독 앵커로 두면 이런 문장이 전부 걸렸다(코퍼스 실측 RELIGION 매치의 93%)."""
    assert find_sensitive_religion(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "명절에 받을 선물이에요",
        "계절에 맞는 옷을 찾아요",
        "학생 시절에 쓰던 제품이에요",
        "온도 조절에 실패했어요",
        "주문 거절에 대한 안내가 없어요",
    ],
)
def test_절에는_단어_안에서는_매치_안_된다(text: str) -> None:
    """앵커를 "절에"로 좁혀도 부분 문자열로 찾으면 "명절에"·"계절에"에 걸린다 — 단어 시작 조건이 막는다."""
    assert find_sensitive_religion(text) == []


@pytest.mark.parametrize(
    ("text", "anchor"),
    [
        ("저는 절에 다니는데 육식이 없는 제품인가요", "절에"),
        ("주말마다 절 다니는데 그때 입을 옷이에요", "절 다니"),
        ("어머니가 절을 다니셔서 채식 위주로 주문해요", "절을 다니"),
    ],
)
def test_사찰_뜻으로_쓰인_절은_여전히_매치된다(text: str, anchor: str) -> None:
    results = find_sensitive_religion(text)

    assert _types(results) == ["SENSITIVE_RELIGION"]
    assert results[0].original_value == anchor
