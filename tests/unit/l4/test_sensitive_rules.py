"""l4/sensitive 규칙 기반 탐지 — 기대값은 손으로 쓴 하드코딩 값."""

import pytest
from l4.sensitive import find_sensitive

from privacy_proxy.schemas import DetectionTier, EntityType

H = EntityType.SENSITIVE_HEALTH
S = EntityType.SENSITIVE_SEX_LIFE

POSITIVE = [
    ("저 당뇨 있어요", "당뇨", H),
    ("우울증 약 먹고 있어요", "우울증", H),
    ("임신 중이라서", "임신", H),
    ("처방전 첨부했습니다", "처방전", H),
    # 띄어쓰기 변형
    ("당 뇨 있어요", "당 뇨", H),
    ("우 울 증 약 먹고 있어요", "우 울 증", H),
    ("공황 장애 진단 받았어요", "공황 장애", H),
    ("탈 모 로 치료 중이에요", "탈 모", H),
    ("저 고혈압  있어요", "고혈압", H),
    ("임 신 했어요", "임 신", H),
    # 오타·변형
    ("당뇨 잇어요", "당뇨", H),
    ("당뇨병 진단받았어요", "당뇨병", H),
    ("hiv 양성 판정 받았어요", "hiv", H),
    ("HIV 양성 판정 받았어요", "HIV", H),
    ("고혈압약 복용중입니다", "고혈압", H),
    ("출산 예정이에요", "출산", H),
    ("갱년기 중이라 힘들어요", "갱년기", H),
    ("진단서 제출할게요", "진단서", H),
    # 광고 문구 + 복용 프레임
    ("당뇨에 좋은 영양제 먹고 있어요", "당뇨", H),
    # 건강·성생활 양쪽에 걸리면 건강
    ("발기부전 있어요", "발기부전", H),
    ("피임 중이에요", "피임", H),
    # 성생활 전용
    ("조루 있어요", "조루", S),
    ("콘돔 사용 중이에요", "콘돔", S),
    ("임신테스트기 사용했는데", "임신테스트기", S),
    # 복합어는 전체가 한 스팬
    ("저 아토피 피부염 있어요", "아토피 피부염", H),
    ("당뇨병성 신경병증 진단받았어요", "당뇨병성 신경병증", H),
    ("지루성 두피염 치료받고 있어요", "지루성 두피염", H),
    ("갑상선 기능저하증 있어요", "갑상선 기능저하증", H),
    ("B형 간염 있어요", "B형 간염", H),
    ("b형 간염 판정받았어요", "b형 간염", H),
    ("성기 헤르페스 진단받았어요", "성기 헤르페스", H),
    ("양극성 장애 있어요", "양극성 장애", H),
    # 병/증 접미·숫자형 접두는 포함, 조사는 제외
    ("당뇨병이 있어요", "당뇨병", H),
    ("우울증이 있어요", "우울증", H),
    ("아토피가 있어요", "아토피", H),
    ("고혈압증 있어요", "고혈압증", H),
    ("2형 당뇨 있어요", "2형 당뇨", H),
    ("제2형 당뇨병 진단받았어요", "제2형 당뇨병", H),
    ("타입2 당뇨 있어요", "타입2 당뇨", H),
    ("타입 2 당뇨 있어요", "타입 2 당뇨", H),
    # 비가시 문자·전각 문자는 매칭에만 정규화하고 값은 원문 그대로
    ("당\u200b뇨 있어요", "당\u200b뇨", H),
    ("당\u00a0뇨 있어요", "당\u00a0뇨", H),
    ("당\u3000뇨 있어요", "당\u3000뇨", H),
    ("\uff28\uff29\uff36 양성 판정 받았어요", "\uff28\uff29\uff36", H),
    ("\u3231 당뇨 있어요", "당뇨", H),
    # 사건·복용 프레임
    ("사후피임약 먹었는데 생리가 늦어져요", "사후피임약", H),
    ("콘돔이 찢어져서 피임에 실패했습니다", "콘돔", S),
    ("딜도 사용했어요", "딜도", S),
    # 문장 경계: 소수점·말줄임표는 끊지 않음
    ("당뇨 수치 3.5 있어요", "당뇨", H),
    ("당뇨... 있어요", "당뇨", H),
    ("당뇨… 있어요", "당뇨", H),
    # 범용 시드
    ("ADHD 진단받았어요", "ADHD", H),
    ("저 공황발작 있어요", "공황발작", H),
    ("간암 판정받았어요", "간암", H),
    ("자궁내막증 있어요", "자궁내막증", H),
    ("질염 걸렸어요", "질염", H),
    ("지방간 진단받았어요", "지방간", H),
    ("저 건선 있어요", "건선", H),
    ("청각장애 있어요", "청각장애", H),
    ("낙태 경험 있어요", "낙태", H),
    ("혈액투석 중이에요", "혈액투석", H),
    ("HIV 검사받았어요", "HIV", H),
    ("당뇨 확진 받았어요", "당뇨", H),
    ("성기능장애 있어요", "성기능장애", S),
    ("질건조증 있어요", "질건조증", S),
    ("윤활제 사용했어요", "윤활제", S),
]

NEGATIVE = [
    "우울한 색감",
    "암막커튼",
    "시스템 장애",
    "장애물 있어요",
    "배송 장애 있어요",
    "탈모 케어 샴푸 추천해줘",
    "당뇨에 좋은 식단 알려줘",
    "당뇨에 좋은 식단 있어요?",
    "화상 회의 있어요",
    "하드 디스크 있어요",
    "상위 암호 있어요",
    "위 암막 있어요",
    "처방전 양식 알려주세요",
    "임신 테스트기 사고 싶어요",
    "콘돔 있어요?",
    "시간 암호 있어요",
    "직장 암호 있어요",
    "건 선택 있어요",
    "당뇨 있어요",  # 아래 케이스의 대조군이라 양성이어야 함 → 제외 처리됨
]
NEGATIVE.pop()
# 설명형·명사형("복용 방법", "먹는 법")은 본인 행위 서술이 아님
NEGATIVE += [
    "사후피임약 복용 방법 알려주세요",
    "피임 방법 알려주세요",
    "사후피임약 가격 알려줘",
    "당뇨 환자도 먹고 싶은 음식",
    "혈압약 먹는 법 알려줘",
    "고혈압약 먹는 법 알려줘",
    "스테로이드 연고 바르는 순서",
    "탈모 크림 바르는 순서",
    "인슐린 맞는 법",
    "피임약 먹는 시간",
    "사후피임약 복용법",
    "고혈압약 복용 시 주의사항",
    "아토피 피부염 정보 알려줘",
    "B형 간염 백신 일정 알려줘",
    "\uff25\uff24 테이프 주문했어요",
    "\u2460\u2461\u2462 순서대로 주문해 주세요",
]
# 경계 케이스: 마침표·줄바꿈이 용어와 프레임을 가른다
NEGATIVE += [
    "당뇨에 대해 알려줘. 저는 잘 있어요",
    "당뇨\n있어요",
    "당뇨. 있어요",
]


@pytest.mark.parametrize(("text", "value", "entity_type"), POSITIVE)
def test_positive(text: str, value: str, entity_type: EntityType) -> None:
    found = find_sensitive(text)
    assert [(r.original_value, r.entity_type) for r in found] == [(value, entity_type)]
    r = found[0]
    assert text[r.start_idx : r.end_idx] == value
    assert r.normalized == value
    assert r.tier is DetectionTier.RULE_ANCHORED
    assert r.source == f"L4_{entity_type.value}"
    assert r.confidence is not None
    assert 0.0 <= r.confidence <= 1.0


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative_no_false_positive(text: str) -> None:
    assert find_sensitive(text) == []


def test_event_sentence_multiple_spans() -> None:
    text = (
        "얼마 전 피임기구(콘돔)가 찢어져서 피임 실패를 했는데 사후피임약 복용 골든타임이 궁금합니다"
    )
    found = find_sensitive(text)
    assert [(r.original_value, r.entity_type) for r in found] == [
        ("피임기구", H),
        ("콘돔", S),
        ("피임", H),
        ("사후피임약", H),
    ]
    for r in found:
        assert text[r.start_idx : r.end_idx] == r.original_value


def test_coordinates_in_multi_sentence_text() -> None:
    text = "배송 문의예요. 저 당 뇨 있어요! 그리고 콘돔 사용 중이에요"
    found = find_sensitive(text)
    assert [(r.start_idx, r.end_idx, r.original_value) for r in found] == [
        (11, 14, "당 뇨"),
        (24, 26, "콘돔"),
    ]
    for r in found:
        assert text[r.start_idx : r.end_idx] == r.original_value


def test_segment_id_passthrough() -> None:
    assert find_sensitive("저 당뇨 있어요", segment_id="seg-7")[0].segment_id == "seg-7"
