"""정규식 + 앵커 인식기 테스트. 픽스처는 전부 가상값이다.

형식만으로는 4종이 안 갈리므로 앵커로 판별한다. 주문·송장·고객번호는 앵커
필수, 통관고유부호만 형식이 고유해 앵커 선택. 경쟁 앵커가 더 가까우면 양보.
"""

import pytest
from l4.recognizers import (
    find_account_number,
    find_address_detail,
    find_address_lot,
    find_address_road,
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
    # 안 갈라져서 그 자체로 배제된다(아래 test_사업자등록번호 참고).
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
        DetectedPII(entity_type="X", original_value="y", start_idx=0, end_idx=1)


def test_통관고유부호_confidence_상한_1로_잘린다() -> None:
    # base 0.85 + bonus 0.35 = 1.2 → 1.0 으로 클램프
    results = find_customs_clearance_id("개인통관고유부호 P123456789012")

    assert results[0].confidence == 1.0


# ── EXCLUDE_PATTERNS ──────────────────────────


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


# ── 유니코드 경계(\b 대체) ──────────────────────────
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


# ── ACCOUNT_NUMBER ──────────────────────────────


def test_계좌번호_3그룹_은행명_앵커와_함께_매치() -> None:
    results = find_account_number("국민은행 123456-01-987654로 환불해주세요")

    assert _types(results) == ["ACCOUNT_NUMBER"]
    assert results[0].original_value == "123456-01-987654"


def test_계좌번호_줄임말_앵커도_매치_하고_3그룹_2그룹_안_겹친다() -> None:
    """ "우리"처럼 은행명이 일반 단어와 겹쳐도 앵커로 쓴다.

    "123-456-789012"의 뒷부분 "456-789012"도 2그룹 형태를 만족하지만, 같은
    계좌번호를 두 번 잡으면 안 된다 — 3그룹 결과 하나만 남아야 한다.
    """
    results = find_account_number("우리 123-456-789012로 보내주세요")

    assert len(results) == 1
    assert results[0].entity_type == "ACCOUNT_NUMBER"
    assert results[0].original_value == "123-456-789012"
    assert results[0].confidence > 0.35  # 3그룹 base_score(0.45) 계열이어야 한다


def test_계좌번호_형식_숫자가_없으면_줄임말_앵커만으로_오탐_안_함() -> None:
    """계좌번호 형식 후보 자체가 없으면 "우리" 앵커가 있어도 아무 일도 안 난다."""
    assert find_account_number("우리 이거 언제 배송돼요?") == []


def test_계좌번호_예금주_앵커와_함께_매치() -> None:
    results = find_account_number("신한 110-234-567890 예금주 확인 부탁드려요")

    assert _types(results) == ["ACCOUNT_NUMBER"]
    assert results[0].original_value == "110-234-567890"


def test_주문번호는_계좌번호로_오매치_안_함() -> None:
    """ "20260830-1234567"은 2그룹 형태와 자릿수가 안 맞아 후보 자체가 안 생긴다."""
    assert find_account_number("주문번호 20260830-1234567") == []


def test_카카오뱅크_7자리_그룹_회귀() -> None:
    """실제 CS 검증 문장. 마지막 그룹 7자리라 초안 {2,6} 폭으로는 안 잡혔었다."""
    results = find_account_number("카카오뱅크 3333-01-9872112로 입금 요망")

    assert _types(results) == ["ACCOUNT_NUMBER"]
    assert results[0].original_value == "3333-01-9872112"


def test_하이픈_포함_사업자번호는_앵커_없으면_계좌번호로_안_잡힌다() -> None:
    assert find_account_number("765-98-83000") == []


def test_계좌번호_은행_자릿수_조합_일치시_confidence_가산() -> None:
    """국민 특유의 (3,2,4) 조합 + "국민" 앵커가 겹치면 보너스가 붙는다.

    "농협"은 같은 자릿수·같은 앵커 거리지만 (3,2,4) 조합이 표에 없어 보너스가
    안 붙는다 — 두 결과의 confidence 차이가 곧 보너스 크기여야 한다.
    """
    with_bonus = find_account_number("국민 345-67-8901로 보내주세요")
    without_bonus = find_account_number("농협 345-67-8901로 보내주세요")

    assert with_bonus[0].confidence - without_bonus[0].confidence == pytest.approx(0.12)


def test_계좌번호_표에_없는_조합도_여전히_매치된다() -> None:
    """카카오뱅크는 은행별 자릿수 표에 없다 — 보너스는 안 붙어도 emit은 된다."""
    results = find_account_number("카카오뱅크 3333-01-9872112로 입금 요망")

    assert _types(results) == ["ACCOUNT_NUMBER"]


# ── 이메일 오탐 배제 ─────────────────────────────────────────────────────
# ID 패턴들의 ASCII 경계 규칙이 '@'/'.'/'-'를 전부 비영숫자로 쳐서, 이메일
# 안의 라벨(로컬파트·도메인·TLD) 하나하나가 독립된 후보로 오탐될 수 있었다.


def test_이메일_로컬파트가_송장번호로_오매치_안_함() -> None:
    """ "solution"(corp-solution의 일부)이 TRACKING_NUMBER 형식과 우연히 일치하던 버그."""
    assert find_tracking_number("이메일: sjpark@corp-solution.co.kr") == []


def test_이메일_배제가_다른_정상_탐지를_방해하지_않는다() -> None:
    results = find_customer_id("고객번호 CU847213, 이메일: test@example.com")

    assert _types(results) == ["CUSTOMER_ID"]
    assert results[0].original_value == "CU847213"


def test_긴_TLD_이메일도_배제된다() -> None:
    """ ".solutions"처럼 TLD가 2자보다 길어도(TLD 폭을 {2,}로 열어둠) 전체가 배제된다."""
    assert find_tracking_number("문의처: contact@shop.solutions") == []


# ── 주소 3종 ────────────────────────────────────────────────
# 건물번호/"번지"·"산"/"동"·"호"·"층"이 정규식 리터럴 자체에 필수라 앵커 조회가
# 없다 — 그 문자열이 곧 자격 조건이다.


def test_도로명_건물번호와_함께_매치() -> None:
    results = find_address_road("테헤란로 152에서 만나요")

    assert _types(results) == ["ADDRESS_ROAD"]
    assert results[0].original_value == "테헤란로 152"


def test_지선도로명_로N길_형태도_매치() -> None:
    """ "성수이로7길"처럼 로 뒤에 지선번호+길이 붙는 도로명주소 표준 명명법.

    초안 정규식은 이걸 "성수이로7"(건물번호로 오인, "길"·실제 건물번호 "12"
    유실)로 잘못 잘랐다 — `(?:\\d{1,3}길)?`을 끼워 지선도로명을 통째로 포함.
    """
    results = find_address_road("성수이로7길 12번 건물이요")

    assert _types(results) == ["ADDRESS_ROAD"]
    assert results[0].original_value == "성수이로7길 12"


def test_도로명_조사가_바로_붙어도_매치() -> None:
    """ "152로"의 "로"는 조사. \\b 유니코드 버그 회귀 방지."""
    results = find_address_road("테헤란로152로 오시면 됩니다")

    assert _types(results) == ["ADDRESS_ROAD"]
    assert results[0].original_value == "테헤란로152"


def test_건물번호_없으면_도로명_매치_안_함() -> None:
    """ "종로"처럼 건물번호 없이 도로명만 오면 지명일 위험 — emit 안 함."""
    assert find_address_road("종로에서 약속 있어요") == []


def test_지번_번지_매치() -> None:
    results = find_address_lot("123-4번지에 거주합니다")

    assert _types(results) == ["ADDRESS_LOT"]
    assert results[0].original_value == "123-4번지"


def test_지번_산_매치() -> None:
    results = find_address_lot("산 15-1에 위치한 임야입니다")

    assert _types(results) == ["ADDRESS_LOT"]
    assert results[0].original_value == "산 15-1"


def test_번지_없으면_주문번호_형식이_지번으로_안_잡힌다() -> None:
    assert find_address_lot("20260830-1234가 제 주문번호예요") == []


def test_상세주소_동호_매치() -> None:
    results = find_address_detail("101동 1502호로 배송해주세요")

    assert _types(results) == ["ADDRESS_DETAIL"]
    assert results[0].original_value == "101동 1502호"
    assert results[0].confidence == 0.6


def test_상세주소_호만_매치() -> None:
    results = find_address_detail("1502호인데요")

    assert _types(results) == ["ADDRESS_DETAIL"]
    assert results[0].original_value == "1502호"
    assert results[0].confidence == 0.45


def test_상세주소_조사가_바로_붙어도_매치() -> None:
    results = find_address_detail("1502호이고")

    assert _types(results) == ["ADDRESS_DETAIL"]
    assert results[0].original_value == "1502호"


def test_상세주소_층만_있으면_confidence_낮다() -> None:
    results = find_address_detail("18층 문 앞에 놔주세요")

    assert _types(results) == ["ADDRESS_DETAIL"]
    assert results[0].original_value == "18층"
    assert results[0].confidence == 0.25


def test_상세주소_일반_서술도_매치되지만_confidence_가장_낮다() -> None:
    """ "3층짜리 건물이에요"는 사실 오탐에 가깝다 — 인지하되 낮은 confidence로 남긴다."""
    results = find_address_detail("이 건물은 3층짜리예요")

    assert _types(results) == ["ADDRESS_DETAIL"]
    assert results[0].confidence == 0.25
    assert results[0].confidence < 0.45  # 호/동호 갈래보다 뚜렷이 낮다
