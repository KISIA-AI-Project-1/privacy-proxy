"""정규식 + 앵커 인식기 테스트. 픽스처는 전부 가상값이다.

형식만으로는 4종이 안 갈리므로 앵커로 판별한다. 주문·송장·고객번호는 앵커
필수, 통관고유부호만 형식이 고유해 앵커 선택. 경쟁 앵커가 더 가까우면 양보.
"""

import pytest
from l4.recognizers import (
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)
from l4.recognizers.recognizers import _excluded, _is_phone_number
from pydantic import ValidationError

from privacy_proxy.schemas import DetectedPII, DetectionTier


def _types(results: list[DetectedPII]) -> list[str]:
    return [r.entity_type for r in results]


def test_통관고유부호_앵커와_함께_매치() -> None:
    results = find_customs_clearance_id("개인통관고유부호 P123456789012 입니다")

    assert _types(results) == ["CUSTOMS_CLEARANCE_ID"]
    assert results[0].original_value == "P123456789012"


def test_주문번호_하이픈_포함_매치() -> None:
    results = find_order_id("주문번호 20260830-1234567 확인 부탁드려요")

    assert _types(results) == ["ORDER_ID"]
    assert results[0].original_value == "20260830-1234567"


def test_순수_날짜는_주문번호가_아니다() -> None:
    assert find_order_id("어제 20260830에 주문했어요") == []
    # 뒤에 하이픈+숫자가 없는 날짜 형태는 앵커가 있어도 배제한다
    assert find_order_id("주문번호 20260830 접수됐어요") == []


def test_송장번호_앵커와_함께_매치() -> None:
    # 10자리 순수 숫자는 안 쓴다 — 사업자등록번호(하이픈 없는 10자리) 배제 패턴과
    # 안 갈라져서 그 자체로 배제된다(L3 회신 반영, 아래 test_사업자등록번호 참고).
    results = find_tracking_number("송장번호 123456789012 확인해주세요")

    assert _types(results) == ["TRACKING_NUMBER"]
    assert results[0].original_value == "123456789012"


def test_앵커_없으면_주문_송장_고객번호는_매치_안_함() -> None:
    assert find_order_id("1234567890") == []
    assert find_tracking_number("1234567890") == []
    assert find_customer_id("1234567890") == []


def test_통관고유부호는_앵커_없어도_매치된다() -> None:
    """P+12자리 형식이 고유해 앵커 단어 없이도 잡는다. confidence는 base_score."""
    results = find_customs_clearance_id("P123456789012 확인해주세요")

    assert _types(results) == ["CUSTOMS_CLEARANCE_ID"]
    assert results[0].confidence == 0.85


def test_고객번호_앵커와_함께_매치() -> None:
    results = find_customer_id("고객번호 CU847213 확인 부탁드려요")

    assert _types(results) == ["CUSTOMER_ID"]
    assert results[0].original_value == "CU847213"


def test_주문번호_앵커만_있으면_고객번호_아님() -> None:
    assert find_customer_id("주문번호 CU847213번으로 조회해주세요") == []


def test_경쟁_앵커가_더_가까우면_고객번호_배제() -> None:
    """자기 앵커(고객번호)는 있지만 주문번호 앵커가 값에 더 붙어 있다."""
    assert find_customer_id("주문번호 CU847213 관련 고객번호로 문의드려요") == []


def test_전화번호는_전_타입_배제() -> None:
    text = "010-0000-0000로 연락주세요"

    assert find_customer_id(text) == []
    assert find_order_id(text) == []
    assert find_tracking_number(text) == []


def test_confidence는_항상_채워지고_범위_안이다() -> None:
    # develop 머지본 schemas.py: confidence는 Field(..., ge=0.0, le=1.0) —
    # 기본값 없음, 빠뜨리면 즉시 ValidationError(아래 테스트로 확인). 인식기는
    # 반드시 score()로 채운다.
    results = find_customer_id("고객번호 CU847213 확인")

    assert len(results) == 1
    pii = results[0]
    assert 0.0 <= pii.confidence <= 1.0
    assert pii.confidence > 0.35  # 앵커가 가까우면 base_score보다 높다
    assert pii.tier is DetectionTier.RULE_ANCHORED
    assert pii.source == "L4_RECOGNIZER_CUSTOMER"
    assert pii.normalized == pii.original_value


def test_confidence_빠뜨리면_ValidationError() -> None:
    """스키마 계약 자체를 확인 — recognizers가 아니라 DetectedPII의 제약이다.

    mypy는 confidence 누락을 정적으로도 잡는다(그래서 recognizers 코드에서
    이 실수는 커밋 전에 걸러진다). 여기서 보려는 건 pydantic의 런타임 검증
    쪽이라 의도적으로 무시한다.
    """
    with pytest.raises(ValidationError):
        DetectedPII(entity_type="X", original_value="y", start_idx=0, end_idx=1)  # type: ignore[call-arg]


def test_통관고유부호_confidence_상한_1로_잘린다() -> None:
    # base 0.85 + bonus 0.35 = 1.2 → 1.0 으로 클램프
    results = find_customs_clearance_id("개인통관고유부호 P123456789012")

    assert results[0].confidence == 1.0


# ── L3 회신 반영: EXCLUDE_PATTERNS (2026-09-11) ──────────────────────────


def test_유효한_주민등록번호는_배제된다() -> None:
    text = "고객 주민번호 901231-1234567 확인"
    start = text.index("901231-1234567")

    assert _excluded(text, start, start + len("901231-1234567"))


def test_월일이_무효하면_주민등록번호로_배제되지_않는다() -> None:
    """자릿수는 RRN 모양이지만 월=99·일=99라 실제로는 아니다."""
    text = "번호 999999-1234567 문의"
    start = text.index("999999-1234567")

    assert not _excluded(text, start, start + len("999999-1234567"))


def test_외국인등록번호도_배제된다() -> None:
    """RRN과 동일 자리수, 성별코드만 5~8."""
    text = "외국인등록번호 901231-5234567 확인"
    start = text.index("901231-5234567")

    assert _excluded(text, start, start + len("901231-5234567"))


def test_사업자등록번호는_하이픈_유무_둘_다_배제된다() -> None:
    text_with_dash = "사업자번호 123-45-67890 입니다"
    start = text_with_dash.index("123-45-67890")
    assert _excluded(text_with_dash, start, start + len("123-45-67890"))

    text_bare = "사업자번호 1234567890 입니다"
    start = text_bare.index("1234567890")
    assert _excluded(text_bare, start, start + len("1234567890"))


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("010-0000-0000", True),
        ("01000000000", True),
        ("CU847213", False),
        ("0000", False),
    ],
)
def test_전화번호_유효성_검사(candidate: str, expected: bool) -> None:
    assert _is_phone_number(candidate) is expected


# ── \b 유니코드 경계 버그 수정 확인 (2026-09-11) ──────────────────────────
#
# Python re는 한글 음절도 \w로 쳐서, "P220194827163으로"처럼 조사가 공백 없이
# 바로 붙으면(한국어 CS 문장에서 일상적) \b가 숫자-한글 경계에서 성립하지
# 않아 후보 자체가 안 생겼다. PATTERNS·ORDER_ID_DATE_EXCLUDE의 \b를 ASCII
# 영숫자 기준 lookaround로 바꿔서 고쳤다.


def test_조사가_바로_붙어도_통관고유부호_매치() -> None:
    results = find_customs_clearance_id("개인통관고유부호 P220194827163으로 수입 신고 완료된 건")

    assert _types(results) == ["CUSTOMS_CLEARANCE_ID"]
    assert results[0].original_value == "P220194827163"


def test_조사가_바로_붙어도_고객번호_매치() -> None:
    results = find_customer_id("고객번호는 NO-559124야")

    assert _types(results) == ["CUSTOMER_ID"]
    assert results[0].original_value == "NO-559124"


def test_조사가_바로_붙어도_주문번호_매치() -> None:
    results = find_order_id("주문번호 20260830-1234567이고")

    assert _types(results) == ["ORDER_ID"]
    assert results[0].original_value == "20260830-1234567"


def test_조사가_바로_붙어도_송장번호_매치() -> None:
    results = find_tracking_number("운송장 ABCD12345678으로 조회")

    assert _types(results) == ["TRACKING_NUMBER"]
    assert results[0].original_value == "ABCD12345678"
