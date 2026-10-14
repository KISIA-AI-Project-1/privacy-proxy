"""정규식 후보 → 앵커 검증 → ``DetectedPII`` 방출.

공통 처리 순서(ID 4종):

1. 형식 정규식으로 후보를 뽑는다.
2. L3 담당 형식(전화·주민·사업자번호)이 후보를 통째로 감싸면 버린다.
   ORDER_ID는 순수 날짜도 버린다. 부분 겹침은 recall 우선으로 남긴다.
3. (CUSTOMER_ID만) ORDER_ID/TRACKING_NUMBER 앵커가 더 가까우면 버린다 —
   형식으로 못 가리니 문맥 우선순위로 가린다.
4. 자기 타입 앵커가 윈도우 안에 없으면 버린다.
   예외: CUSTOMS_CLEARANCE_ID는 형식이 고유해 앵커가 선택이다 — 없으면
   confidence를 base_score로 낮춰서 그대로 방출한다.
5. ``DetectedPII`` 생성. tier=RULE_ANCHORED, normalized=원문 그대로.

``find_account_number``는 3그룹/2그룹 두 형식이 같은 숫자열에서 겹쳐 매치될
수 있어 3그룹을 먼저 처리하고, 2그룹은 겹치는 span을 버린다.

주소 3종(``find_address_road``/``lot``/``detail``)은 이 순서를 안 탄다 —
건물번호·"번지"/"산"·"동"/"호"/"층"이 정규식 리터럴 자체에 필수라 그 문자열이
곧 자격 조건이라서다. 숫자만으로는 뭔지 알 수 없는 ID류와 달리 그 자체로
의미가 확정되므로 앵커 조회가 필요 없다. confidence도 앵커 거리 기반
``score()``가 아니라 형식(또는 DETAIL의 갈래)별 고정값이다.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache

import phonenumbers
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from l4.recognizers.anchors import ANCHORS
from l4.recognizers.context import has_anchor, score
from l4.recognizers.patterns import (
    ACCOUNT_NUMBER_2GRP,
    ACCOUNT_NUMBER_3GRP,
    ADDRESS_DETAIL_PATTERN,
    ADDRESS_LOT_PATTERN,
    ADDRESS_ROAD_PATTERN,
    BANK_DIGIT_GROUPS,
    EXCLUDE_PATTERNS,
    ORDER_ID_DATE_EXCLUDE,
    PATTERNS,
)
from privacy_proxy.l3.email_validation import configure_email
from privacy_proxy.schemas import DetectedPII, DetectionTier

_WINDOW = 25

# 갈래별 confidence. 동+호가 가장 구체적이고, 층 단독은
# "3층짜리 건물이에요" 같은 일반 서술과 안 갈려 가장 낮다.
_ADDRESS_DETAIL_CONFIDENCE: dict[str, float] = {
    "dongho": 0.6,
    "ho": 0.45,
    "floor": 0.25,
}


@cache
def _email_recognizer() -> EmailRecognizer:
    producer = EmailRecognizer(supported_language="ko")
    configure_email(producer)
    return producer


@lru_cache(maxsize=32)
def _l3_spans(text: str) -> tuple[tuple[int, int], ...]:
    """L3와 같은 설정의 전화번호(KR, leniency=1)·이메일 탐지 구간."""
    phones = phonenumbers.PhoneNumberMatcher(text, "KR", leniency=1)
    emails = _email_recognizer().analyze(text, ["EMAIL_ADDRESS"])
    return tuple((m.start, m.end) for m in phones) + tuple((r.start, r.end) for r in emails)


def _excluded(text: str, start: int, end: int) -> bool:
    """후보 span이 L3 담당 형식이면 True.

    원문 위치 기준으로 판단한다 — 후보 문자열만 보면 CUSTOMER_ID처럼 숫자열만
    남는 후보에서 전화번호 배제가 안 걸리는 경우가 있다(예: "010-0000-0000"의
    "0000"). L3 형식이 후보를 통째로 감쌀 때만 배제하고 부분 겹침은 남긴다.
    전화번호·이메일은 정규식 목록이 아니라 L3 인식기 설정을 그대로 쓴다.
    """
    for pattern in EXCLUDE_PATTERNS:
        for hit in pattern.finditer(text):
            if hit.start() <= start and hit.end() >= end:
                return True
    return any(s <= start and e >= end for s, e in _l3_spans(text))


def _emit(
    entity_type: str,
    source: str,
    base_score: float,
    match: re.Match[str],
    distance: int,
    segment_id: str,
    bonus: float = 0.0,
) -> DetectedPII:
    value = match.group()
    confidence = min(1.0, score(base_score, distance) + bonus)
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        normalized=value,
        start_idx=match.start(),
        end_idx=match.end(),
        confidence=confidence,
        segment_id=segment_id,
        tier=DetectionTier.RULE_ANCHORED,
        source=source,
    )


def _find_anchored(
    entity_type: str,
    source: str,
    base_score: float,
    text: str,
    segment_id: str,
    extra_exclude: re.Pattern[str] | None = None,
) -> list[DetectedPII]:
    """앵커 필수인 2종(주문·송장) 공통 로직. 경쟁 앵커 배제는 없다."""
    results: list[DetectedPII] = []
    for match in PATTERNS[entity_type].finditer(text):
        if _excluded(text, match.start(), match.end()):
            continue
        if extra_exclude is not None and extra_exclude.search(match.group()):
            continue
        found, distance = has_anchor(
            text, match.start(), match.end(), ANCHORS[entity_type], _WINDOW
        )
        if not found:
            continue
        results.append(_emit(entity_type, source, base_score, match, distance, segment_id))
    return results


def find_customs_clearance_id(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """통관고유부호만 앵커가 선택이다 — 형식이 고유해 앵커 없는 메시지도
    놓치면 안 된다. 앵커가 있으면 confidence를 가산하고 없으면 base_score
    그대로 쓴다.
    """
    results: list[DetectedPII] = []
    for match in PATTERNS["CUSTOMS_CLEARANCE_ID"].finditer(text):
        if _excluded(text, match.start(), match.end()):
            continue
        found, distance = has_anchor(
            text, match.start(), match.end(), ANCHORS["CUSTOMS_CLEARANCE_ID"], _WINDOW
        )
        # 앵커 없으면 거리 = window → score()가 base_score를 그대로 돌려준다.
        results.append(
            _emit(
                "CUSTOMS_CLEARANCE_ID",
                "L4_RECOGNIZER_CUSTOMS",
                0.85,
                match,
                distance if found else _WINDOW,
                segment_id,
            )
        )
    return results


def find_order_id(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_anchored(
        "ORDER_ID", "L4_RECOGNIZER_ORDER", 0.5, text, segment_id, ORDER_ID_DATE_EXCLUDE
    )


def find_tracking_number(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    return _find_anchored("TRACKING_NUMBER", "L4_RECOGNIZER_TRACKING", 0.4, text, segment_id)


def find_customer_id(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """CUSTOMER_ID만 경쟁 앵커 배제가 붙는다."""
    results: list[DetectedPII] = []
    for match in PATTERNS["CUSTOMER_ID"].finditer(text):
        if _excluded(text, match.start(), match.end()):
            continue

        self_found, self_dist = has_anchor(
            text, match.start(), match.end(), ANCHORS["CUSTOMER_ID"], _WINDOW
        )
        if not self_found:
            continue

        order_found, order_dist = has_anchor(
            text, match.start(), match.end(), ANCHORS["ORDER_ID"], _WINDOW
        )
        if order_found and order_dist < self_dist:
            continue

        tracking_found, tracking_dist = has_anchor(
            text, match.start(), match.end(), ANCHORS["TRACKING_NUMBER"], _WINDOW
        )
        if tracking_found and tracking_dist < self_dist:
            continue

        results.append(
            _emit(
                "CUSTOMER_ID",
                "L4_RECOGNIZER_CUSTOMER",
                0.35,
                match,
                self_dist,
                segment_id,
            )
        )
    return results


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


_BANK_DIGIT_BONUS = 0.12  # 은행 자릿수 조합 일치 시 가산. 확정 판정 아님.
_NO_BANK_SUFFIX = {"우체국", "새마을금고"}  # "은행" 접미사를 안 쓰는 예외


def _bank_digit_bonus(text: str, start: int, end: int, value: str) -> float:
    """은행명 앵커 + 그 은행 특유의 자릿수 조합이 겹치면 소량 가산.

    표에 없는 조합이거나 은행명이 안 잡히면 0을 돌려줄 뿐, emit 여부 자체는
    호출 전 단계(그룹 수·기본 앵커 필수)에서 이미 정해져 있어 recall에는
    영향 없다.
    """
    groups = tuple(len(part) for part in value.split("-"))
    for bank, combos in BANK_DIGIT_GROUPS.items():
        if groups not in combos:
            continue
        aliases = [bank] if bank in _NO_BANK_SUFFIX else [bank, bank + "은행"]
        found, _ = has_anchor(text, start, end, aliases, _WINDOW)
        if found:
            return _BANK_DIGIT_BONUS
    return 0.0


def find_account_number(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """계좌번호. 3그룹과 2그룹 두 형식이 같은 숫자열에서 겹쳐 매치될 수 있어
    (예: "1002-841-928102"의 "841-928102"가 2그룹도 만족) 3그룹을 먼저 잡고
    2그룹은 겹치는 span을 버린다.
    """
    results: list[DetectedPII] = []
    covered: list[tuple[int, int]] = []

    for match in ACCOUNT_NUMBER_3GRP.finditer(text):
        if _excluded(text, match.start(), match.end()):
            continue
        found, distance = has_anchor(
            text, match.start(), match.end(), ANCHORS["ACCOUNT_NUMBER"], _WINDOW
        )
        if not found:
            continue
        bonus = _bank_digit_bonus(text, match.start(), match.end(), match.group())
        results.append(
            _emit(
                "ACCOUNT_NUMBER",
                "L4_RECOGNIZER_ACCOUNT",
                0.45,
                match,
                distance,
                segment_id,
                bonus,
            )
        )
        covered.append(match.span())

    for match in ACCOUNT_NUMBER_2GRP.finditer(text):
        if any(_overlaps(match.start(), match.end(), s, e) for s, e in covered):
            continue
        if _excluded(text, match.start(), match.end()):
            continue
        found, distance = has_anchor(
            text, match.start(), match.end(), ANCHORS["ACCOUNT_NUMBER"], _WINDOW
        )
        if not found:
            continue
        results.append(
            _emit("ACCOUNT_NUMBER", "L4_RECOGNIZER_ACCOUNT", 0.35, match, distance, segment_id)
        )

    return results


def _emit_fixed(
    entity_type: str,
    source: str,
    confidence: float,
    match: re.Match[str],
    segment_id: str,
) -> DetectedPII:
    """고정 confidence로 방출 — 주소 3종 전용. 자격 조건이 정규식 리터럴 자체에
    있어 앵커 거리라는 개념이 없다.
    """
    value = match.group()
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        normalized=value,
        start_idx=match.start(),
        end_idx=match.end(),
        confidence=confidence,
        segment_id=segment_id,
        tier=DetectionTier.RULE_ANCHORED,
        source=source,
    )


def find_address_road(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """도로명 + 건물번호. 건물번호가 필수라 "종로에서"처럼 번호 없이 도로명만
    오면 후보 자체가 안 생겨 고유명사 오탐을 형식으로 차단한다.
    """
    return [
        _emit_fixed("ADDRESS_ROAD", "L4_RECOGNIZER_ADDRESS_ROAD", 0.5, match, segment_id)
        for match in ADDRESS_ROAD_PATTERN.finditer(text)
    ]


def find_address_lot(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """지번. "번지"/"산" 리터럴 자체가 자격 조건이라 순수 숫자-숫자(주문번호
    형식 등)는 후보가 안 생긴다.
    """
    return [
        _emit_fixed(
            "ADDRESS_LOT",
            "L4_RECOGNIZER_ADDRESS_LOT",
            0.45 if match["dong"] else 0.7,
            match,
            segment_id,
        )
        for match in ADDRESS_LOT_PATTERN.finditer(text)
    ]


def find_address_detail(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """동/호/층. 세 갈래(동+호/호만/층만)로 오탐 위험이 달라 confidence를 나눈다.

    ``ADDRESS_DETAIL_PATTERN`` 의 named group으로 어느 갈래가 매치됐는지 판별한다.
    """
    results: list[DetectedPII] = []
    for match in ADDRESS_DETAIL_PATTERN.finditer(text):
        branch = match.lastgroup
        if branch is None:
            continue  # 이론상 안 옴 — 세 named group 중 하나는 항상 매치된다.
        confidence = _ADDRESS_DETAIL_CONFIDENCE[branch]
        results.append(
            _emit_fixed(
                "ADDRESS_DETAIL", "L4_RECOGNIZER_ADDRESS_DETAIL", confidence, match, segment_id
            )
        )
    return results
