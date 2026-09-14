"""정규식 후보 → 앵커 검증 → ``DetectedPII`` 방출.

처리 순서(모든 타입 공통):

1. 형식 정규식으로 후보를 뽑는다.
2. L3 담당 형식(전화·주민·사업자번호)이 후보를 통째로 감싸면 버린다.
   ORDER_ID는 순수 날짜도 여기서 버린다.
3. (CUSTOMER_ID만) 경쟁 앵커 배제 — ORDER_ID/TRACKING_NUMBER 앵커가 자기
   앵커보다 값에 더 가까우면 버린다. 형식으로 못 가리니 문맥 우선순위로 가린다.
4. 자기 타입 앵커가 윈도우 안에 없으면 버린다.
   **예외: CUSTOMS_CLEARANCE_ID는 형식이 고유해 앵커가 선택이다.** 앵커가
   없으면 confidence만 base_score로 낮춰서 그대로 방출한다.
5. ``DetectedPII`` 생성. tier=RULE_ANCHORED, normalized=원문 그대로(조사 결합 없음).

L4 recall 우선: 부분만 겹치는 L3 형식은 배제하지 않고 남긴다(2번의 "통째로").

``find_account_number`` (계좌번호)만 위 순서에 하나 더 낀다 — 3그룹/2그룹 두
형식이 같은 숫자열에서 겹쳐 매치될 수 있어서, 3그룹을 먼저 처리하고 2그룹은
이미 잡힌 3그룹 span과 겹치면 버린다(``find_account_number`` docstring 참고).
"""

from __future__ import annotations

import re

import phonenumbers

from l4.recognizers.anchors import ANCHORS
from l4.recognizers.context import has_anchor, score
from l4.recognizers.patterns import (
    ACCOUNT_NUMBER_2GRP,
    ACCOUNT_NUMBER_3GRP,
    EXCLUDE_PATTERNS,
    ORDER_ID_DATE_EXCLUDE,
    PATTERNS,
)
from privacy_proxy.schemas import DetectedPII, DetectionTier

_WINDOW = 25


def _is_phone_number(candidate: str) -> bool:
    """후보 문자열 자체가 유효한 한국 전화번호인지. L3와 동일하게 phonenumbers를 쓴다.

    정규식 자릿수만으로는 전화번호와 우리 ID들을 안전하게 못 가른다(둘 다
    숫자 8~11자리). 실제 유효성 검사(지역/구분 코드 포함)로 판별한다.
    """
    try:
        parsed = phonenumbers.parse(candidate, "KR")
    except phonenumbers.NumberParseException:
        return False
    # phonenumbers는 타입 스텁이 부실해서 is_valid_number()가 Any로 잡힌다.
    is_valid: bool = phonenumbers.is_valid_number(parsed)
    return is_valid


def _excluded(text: str, start: int, end: int) -> bool:
    """후보 span ``[start, end)`` 이 L3 담당 형식이면 True.

    주민/외국인등록번호·사업자등록번호는 원문 위치 기준 — 후보 문자열만 검사하면
    (초안 방식) CUSTOMER_ID처럼 숫자열만 남는 후보에서 전화번호 배제가 안 걸리는
    경우가 있어서다(예: "010-0000-0000"의 "0000"). L3 형식이 후보를 통째로
    감쌀 때만 배제하고, 부분 겹침은 recall 우선으로 남긴다.

    전화번호는 정규식 매치가 실패하면 후보 문자열 자체를 ``_is_phone_number``로
    한 번 더 확인한다(정규식 배제 목록엔 전화번호가 없다).
    """
    for pattern in EXCLUDE_PATTERNS:
        for hit in pattern.finditer(text):
            if hit.start() <= start and hit.end() >= end:
                return True
    return _is_phone_number(text[start:end])


def _emit(
    entity_type: str,
    source: str,
    base_score: float,
    match: re.Match[str],
    distance: int,
    segment_id: str,
) -> DetectedPII:
    value = match.group()
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        normalized=value,
        start_idx=match.start(),
        end_idx=match.end(),
        confidence=score(base_score, distance),
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
    """통관고유부호만 앵커가 선택이다.

    ``\\b[Pp]\\d{12}\\b`` 형식이 충분히 고유해 앵커 단어 없는 CS 메시지
    ("P123456789012 확인해주세요")도 놓치면 안 된다. 앵커가 있으면 confidence를
    가산하고, 없으면 base_score(0.85)를 그대로 쓴다.
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


def find_account_number(text: str, segment_id: str = "seg-1") -> list[DetectedPII]:
    """계좌번호. 3그룹(예: 123456-01-987654)과 2그룹(예: 123-456789) 두 형식.

    두 패턴이 같은 숫자열에서 겹쳐 매치될 수 있다 — "1002-841-928102"(3그룹)의
    뒷부분 "841-928102"가 2그룹 패턴도 만족한다. 3그룹을 먼저 잡고, 2그룹은
    이미 잡힌 3그룹 span과 겹치면 버려서 같은 계좌번호를 두 번 emit하지 않는다.
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
        results.append(
            _emit("ACCOUNT_NUMBER", "L4_RECOGNIZER_ACCOUNT", 0.45, match, distance, segment_id)
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
