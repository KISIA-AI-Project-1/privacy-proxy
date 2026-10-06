"""l4/sensitive 3번(구매 맥락) — 기대값은 손으로 쓴 하드코딩 값."""

import pytest
from l4.sensitive import find_sensitive
from l4.sensitive.engine import find_state

from privacy_proxy.schemas import DetectionTier

ITEM = "PRODUCT_ITEM"
PATTERN = "PURCHASE_PATTERN"
HEALTH = "SENSITIVE_HEALTH"


def got(text: str) -> list[tuple[str, str]]:
    return [(r.entity_type.value, r.original_value) for r in find_sensitive(text)]


GOLDEN = [
    (
        "저 김철수인데요. 3개월 주기 정기배송으로 신청한 탈모치료제 배송지 변경 부탁드립니다."
        " 010-1234-5678입니다.",
        [(PATTERN, "정기배송", 17, 21), (ITEM, "탈모치료제", 28, 33)],
    ),
    (
        "탈모치료제 3개월 주기 정기배송이 계속 늦어요. 확인 부탁드립니다.",
        [(ITEM, "탈모치료제", 0, 5), (PATTERN, "정기배송", 13, 17)],
    ),
    (
        "저번 달에 산 우울증 개선용 영양제 다 먹어가는데, 수면 유도 효과도 있는 걸로 추천해 줘."
        " 배송지는 서울시 관악구 신림동으로 해.",
        [(ITEM, "우울증 개선용 영양제", 8, 19)],
    ),
]


@pytest.mark.parametrize(("text", "expected"), GOLDEN)
def test_golden_coordinates(text: str, expected: list[tuple[str, str, int, int]]) -> None:
    found = find_sensitive(text)
    assert [(r.entity_type.value, r.original_value, r.start_idx, r.end_idx) for r in found] == (
        expected
    )
    for r in found:
        assert text[r.start_idx : r.end_idx] == r.original_value
        assert r.normalized == r.original_value
        assert r.tier is DetectionTier.RULE_ANCHORED
        assert r.source == f"L4_SENSITIVE_{r.entity_type.value}"
        assert r.confidence is not None
        assert 0.0 <= r.confidence <= 1.0


POSITIVE = [
    # 띄어쓰기·표기 변형
    ("탈 모 치료제 주문했어요", [(ITEM, "탈 모 치료제")]),
    ("탈모 치료제 샀어요", [(ITEM, "탈모 치료제")]),
    ("탈모샴푸 구매했어요", [(ITEM, "탈모샴푸")]),
    ("우울증 영양제 시켜놨어요", [(ITEM, "우울증 영양제")]),
    ("우 울 증 개선용 영양제 주문", [(ITEM, "우 울 증 개선용 영양제")]),
    ("고혈압약 환불해주세요", [(ITEM, "고혈압약")]),
    ("당뇨 케어 영양제 반품할게요", [(ITEM, "당뇨 케어 영양제")]),
    ("산 탈모치료제 교환 가능한가요", [(ITEM, "탈모치료제")]),
    ("어제 산 탈모 샴푸 좋아요", [(ITEM, "탈모 샴푸")]),
    ("탈모치료제 정 기 배송 신청", [(ITEM, "탈모치료제"), (PATTERN, "정 기 배송")]),
    ("탈모치료제 재 구매 했어요", [(ITEM, "탈모치료제"), (PATTERN, "재 구매")]),
    ("탈모치료제 정기 결제 해지하고 싶어요", [(ITEM, "탈모치료제"), (PATTERN, "정기 결제")]),
    # 성생활 제품
    ("콘돔 정기배송 신청하고 싶어요", [(ITEM, "콘돔"), (PATTERN, "정기배송")]),
    ("임신테스트기 주문했어요", [(ITEM, "임신테스트기")]),
    ("성인용품 배송 언제 와요", [(ITEM, "성인용품")]),
    # 재구매·해지·신청 의도
    ("탈모치료제 정기배송 해지할게요", [(ITEM, "탈모치료제"), (PATTERN, "정기배송")]),
    ("우울증 영양제 또 주문할게요 매달 시켜요", [(ITEM, "우울증 영양제"), (PATTERN, "또 주문")]),
    ("고혈압약 떨어져서 주문해요", [(ITEM, "고혈압약")]),
    (
        "당뇨약 다 떨어졌어요 지난달이랑 똑같이 주문",
        [(ITEM, "당뇨약"), (PATTERN, "떨어졌"), (PATTERN, "지난달이랑"), (PATTERN, "똑같이")],
    ),
    ("탈모 샴푸 6개월마다 주문해요", [(ITEM, "탈모 샴푸"), (PATTERN, "6개월마다")]),
    ("탈모 샴푸 주 3회 쓰는데 재주문", [(ITEM, "탈모 샴푸"), (PATTERN, "재주문")]),
    ("탈모 샴푸 주 3회 분량으로 주문", [(ITEM, "탈모 샴푸"), (PATTERN, "주 3회")]),
]


@pytest.mark.parametrize(("text", "expected"), POSITIVE)
def test_positive(text: str, expected: list[tuple[str, str]]) -> None:
    assert got(text) == expected
    for r in find_sensitive(text):
        assert text[r.start_idx : r.end_idx] == r.original_value


NEGATIVE = [
    "3번째 줄 확인해주세요",
    "주 2회 운동해요",  # 상품 없음
    "정기배송은 가능합니다",  # 상품 없음
    "탈모 케어 샴푸 추천해줘",  # 구매 맥락 없음
    "암막커튼 정기배송",
    "암막커튼 배송",
    "우울한 색감 커튼 주문",
    "탈모치료제 추천해줘",
    "산 정상에서 탈모 샴푸 추천해줘",  # "산"이 상품 바로 앞이 아님
    "화상회의 영양제 주문",
]


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative_no_false_positive(text: str) -> None:
    assert find_sensitive(text) == []


def test_counselor_line_clue_dropped() -> None:
    assert got("상담사: 탈모치료제 정기배송은 가능합니다") == [(ITEM, "탈모치료제")]
    assert got("상담사: 확인해볼게요\n탈모치료제 정기배송 신청할게요") == [
        (ITEM, "탈모치료제"),
        (PATTERN, "정기배송"),
    ]


def test_two_products_one_clue() -> None:
    assert got("탈모 샴푸는 한 번 샀고 우울증 영양제는 정기배송이에요") == [
        (ITEM, "탈모 샴푸"),
        (ITEM, "우울증 영양제"),
        (PATTERN, "정기배송"),
    ]


def test_clue_does_not_cross_sentence_boundary() -> None:
    assert got("탈모치료제 샀어요. 정기배송은 가능한가요") == [(ITEM, "탈모치료제")]


def test_state_statement_kept_next_to_product() -> None:
    # 첫 "당뇨"는 독립 상태 서술이라 상품 스팬(당뇨약)과 겹치지 않아 유지된다
    text = "당뇨 있어서 당뇨약 주문"
    assert [(r.entity_type.value, r.original_value, r.start_idx) for r in find_sensitive(text)] == [
        (HEALTH, "당뇨", 0),
        (ITEM, "당뇨약", 7),
    ]


def test_overlapping_state_span_replaced_by_product() -> None:
    # 2번 단독으로는 "당뇨"(상품 스팬 안쪽)를 내지만 통합에서는 3번이 우선
    text = "당뇨 영양제 먹고 있어요 주문"
    assert [r.original_value for r in find_state(text)] == ["당뇨"]
    assert got(text) == [(ITEM, "당뇨 영양제")]


def test_gap_that_is_not_a_modifier_gives_no_product() -> None:
    assert got("당뇨 있어서 약 주문") == [(HEALTH, "당뇨")]


def test_state_alone_unchanged_by_integration() -> None:
    assert got("저 당뇨 있어요") == [(HEALTH, "당뇨")]


def test_purchase_frame_discarded_by_state_only() -> None:
    assert find_state("탈모 샴푸 정기배송") == []
    assert got("탈모 샴푸 정기배송") == [(ITEM, "탈모 샴푸"), (PATTERN, "정기배송")]


def test_output_sorted_by_start() -> None:
    text = "저 고혈압 있어요. 탈모치료제 정기배송 주문, 콘돔 샀어요"
    starts = [r.start_idx for r in find_sensitive(text)]
    assert starts == sorted(starts)
    assert len(starts) == 4


def test_segment_id_passthrough() -> None:
    assert find_sensitive("탈모치료제 주문", segment_id="seg-9")[0].segment_id == "seg-9"
