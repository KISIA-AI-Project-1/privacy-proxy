"""Synthetic approved D7 AGE semantics; no real personal data."""

import pytest

from privacy_proxy.l3.age_recognizer import MAX_ANCHOR_DISTANCE, AgeStatementRecognizer


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        ("고객 나이는 32세입니다.", "32세"),
        ("나이: 32세", "32세"),
        ("연령은 만 19세입니다.", "만 19세"),
        ("고객 연령은 45 살입니다.", "45 살"),
        ("제 나이는 만 19세 입니다.", "만 19세"),
        ("고객 연령은 32 세입니다.", "32 세"),
        ("나이:\t만\t19\t세", "만\t19\t세"),
        ("연령 = 25  살", "25  살"),
        ("저는 25살입니다.", "25살"),
        ("제가 25살입니다.", "25살"),
        ("고객은 32세입니다.", "32세"),
        ("고객님은 현재 만 32 살입니다.", "만 32 살"),
        ("저는 올해 25살이에요.", "25살"),
        ("나이: 32세! 연령 제한은 19세입니다.", "32세"),
        ("연령 제한은 19세입니다. 저는 25살입니다.", "25살"),
    ],
)
def test_approved_positive(text, surface):
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert len(results) == 1
    result = results[0]
    assert text[result.start : result.end] == surface
    assert 0 <= result.start < result.end <= len(text)


@pytest.mark.parametrize("number", ["0", "1", "119", "120"])
def test_numeric_inclusive(number):
    text = f"나이: {number}세"
    assert len(AgeStatementRecognizer().analyze(text, ["AGE"])) == 1


@pytest.mark.parametrize(
    "value",
    [
        "121세",
        "032세",
        "00세",
        "-1세",
        "+19세",
        "19.5세",
        "1,019세",
        "1 019세",
        "20~30세",
        "20 ~ 30세",
        "20-30세",
        "20세부터 30세까지",
        "약 30세",
        "대략 30세",
        "30세 정도",
        "30세쯤",
        "３０세",
        "20세기",
        "100세트",
        "20세대",
        "재벌 3세",
        "창업 2세",
        "5살 차이",
        "3세 연하",
        "10세 연상",
        "20대",
        "1995년생",
        "95년생",
        "1990-05-15",
        "생후 6개월",
        "6개월",
        "6개월령",
        "6주",
        "6일",
        "스무 살",
        "twenty years old",
        "19\n세",
        "만\n19세",
    ],
)
def test_anchored_negative(value):
    assert AgeStatementRecognizer().analyze(f"나이: {value}", ["AGE"]) == []


@pytest.mark.parametrize(
    "text",
    [
        "32세",
        "25살",
        "만 19세입니다.",
        "저는 25살",
        "나이",
        "만 19세 이상 이용 가능합니다.",
        "가입 가능 연령은 만 18세 이상입니다.",
        "지원 대상은 20세 이상입니다.",
        "연령 제한은 19세입니다.",
        "나이는 19세 이하입니다.",
        "연령은 19세 미만입니다.",
        "나이 기준은 19세입니다.",
        "저는 25살 차이입니다.",
        "저는 재벌 3세입니다.",
        "고객은 창업 2세입니다.",
    ],
)
def test_bare_policy_and_ambiguous_negative(text):
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


@pytest.mark.parametrize(
    ("separator", "distance"), [(":", 1), (" ", 1), (" " * MAX_ANCHOR_DISTANCE, 15)]
)
def test_window_inclusive(separator, distance):
    text = "나이" + separator + "32세"
    assert text.index("32세") - len("나이") == distance
    assert len(AgeStatementRecognizer().analyze(text, ["AGE"])) == 1


@pytest.mark.parametrize("text", ["나이32세", "저는25살입니다."])
def test_zero_distance_remains_lexically_unsupported(text):
    # Every existing anchor ends in a word character. At distance zero the
    # candidate's unchanged lexical boundary rejects it; do not widen scope.
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


def test_window_exceeded():
    assert AgeStatementRecognizer().analyze("나이" + " " * 16 + "32세", ["AGE"]) == []


@pytest.mark.parametrize("separator", ["\r", "\n", "\r\n", ".", "!", "?"])
def test_anchor_cannot_cross_clause(separator):
    assert AgeStatementRecognizer().analyze("나이" + separator + "32세", ["AGE"]) == []


def test_candidate_cannot_cross_newline():
    assert AgeStatementRecognizer().analyze("나이: 19\n세", ["AGE"]) == []


def test_unrequested_entity():
    assert AgeStatementRecognizer().analyze("나이: 32세", ["EMAIL_ADDRESS"]) == []


@pytest.mark.parametrize("value", ["20세~30세", "20세 - 30세", "20살\u201330살"])
def test_range_does_not_emit_first_endpoint(value):
    assert AgeStatementRecognizer().analyze(f"나이: {value}", ["AGE"]) == []


@pytest.mark.parametrize(
    "text",
    [
        "나이: 30세 내외",
        "나이: 30세 안팎",
        "가입 연령은 18세입니다.",
        "권장 연령은 12세입니다.",
        "나이는 5살 더 많습니다.",
    ],
)
def test_review_blocker_regression(text):
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


@pytest.mark.parametrize("modifier", ["내외", "안팎", "가량", "정도", "전후"])
def test_local_approximation_category(modifier):
    assert AgeStatementRecognizer().analyze(f"연령은 만 31 살 {modifier}입니다.", ["AGE"]) == []


@pytest.mark.parametrize(
    "label",
    [
        "가입 연령",
        "가입가능 연령",
        "가입" + " " * 8 + "가능 연령",
        "권장 나이",
        "연령 제한",
        "이용 기준 연령",
        "지원 대상 나이",
        "신청 연령",
        "법정 연령",
        "의무 가입 연령",
        "적용 연령",
    ],
)
def test_local_policy_category(label):
    assert AgeStatementRecognizer().analyze(f"{label}은 21세입니다.", ["AGE"]) == []


@pytest.mark.parametrize(
    "comparison",
    [
        "더 많습니다",
        "더 적습니다",
        "차이입니다",
        "연상입니다",
        "연하입니다",
        "덜 적습니다",
        "터울입니다",
    ],
)
def test_local_relative_category(comparison):
    assert AgeStatementRecognizer().analyze(f"나이는 4 살 {comparison}.", ["AGE"]) == []


@pytest.mark.parametrize(
    ("text", "surface"),
    [
        ("가입 연령은 18세입니다. 고객 연령은 32세입니다.", "32세"),
        ("나이는 30세 내외입니다. 고객 나이는 42세입니다.", "42세"),
        ("형보다 5살 더 많습니다. 제 나이는 30세입니다.", "30세"),
        ("나이는 5살 더 적습니다! 저는 30살입니다.", "30살"),
        ("나이: 30세 내외, 고객 나이: 42세", "42세"),
        ("가입 연령: 18세, 고객 연령: 32세", "32세"),
        ("나이: 5살 차이, 고객 나이: 42세", "42세"),
    ],
)
def test_semantic_guard_locality(text, surface):
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert [text[r.start : r.end] for r in results] == [surface]


@pytest.mark.parametrize(
    "modifier", ["내외", "안팎", "가량", "정도", "전후", "더 많습니다", "권장"]
)
def test_unrelated_later_modifier_does_not_suppress_personal_age(modifier):
    text = f"고객 나이는 32세입니다, 다른 항목 설명은 {modifier}"
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert [text[r.start : r.end] for r in results] == ["32세"]


def test_post_guard_supported_spacing_bound():
    text = "나이: 30세" + " " * 15 + "더" + " " * 7 + "많습니다."
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


def test_policy_guard_supported_spacing_bound():
    text = "권장" + " " * 15 + "연령은 12세입니다."
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


@pytest.mark.parametrize(
    "text",
    [
        "대략 나이는 30세입니다.",
        "대략 연령은 30살입니다.",
        "약 연령은 30세입니다.",
    ],
)
def test_approximation_immediately_before_anchor_remains_excluded(text):
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


def test_unrelated_earlier_approximation_does_not_suppress_age():
    text = "대략 계산한 금액이고 고객 나이는 32세입니다."
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert [text[r.start : r.end] for r in results] == ["32세"]


@pytest.mark.parametrize(
    "text",
    [
        "고객 나이: 32세 적립금: 1000원",
        "고객 나이: 32세 적성: 음악",
        "고객 나이: 32세 적금: 없음",
        "고객 나이: 32세 적용 항목: 없음",
    ],
)
def test_d2_prefix_collision(text):
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert len(results) == 1
    result = results[0]
    assert 0 <= result.start < result.end <= len(text)
    assert text[result.start : result.end] == "32세"


@pytest.mark.parametrize(
    "text",
    [
        "나이는 5살 더 적습니다.",
        "나이는 5살 더 많습니다.",
        "5살 차이",
        "3세 연하",
        "10세 연상",
        "나이: 5살 차이",
        "나이: 3세 연하",
        "나이: 10세 연상",
        "나이는 5살 적습니다.",
        "나이는 5살 많다.",
        "나이는 5살 더 많은 편입니다.",
        "나이는 5살 더 적게 기록됐습니다.",
        "나이는 5살 덜 적어요.",
    ],
)
def test_d2_relative_rejection(text):
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


@pytest.mark.parametrize(
    "text",
    [
        "나이는 5살 더 많았어요.",
        "나이는 5살 더 적지만 성인입니다.",
        "나이는 5살 더 많지만 학생입니다.",
        "나이는 5살 더 많았지만 지금은 비교하지 않습니다.",
        "나이는 5살 더 적어서 해당되지 않습니다.",
        "나이는 5살 덜 적었겠지요.",
    ],
)
def test_d3_comparative_structure(text):
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


def test_d3_prefix_collision():
    text = "고객 나이: 32세 적응 상태: 양호"
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert len(results) == 1
    assert 0 <= results[0].start < results[0].end <= len(text)
    assert text[results[0].start : results[0].end] == "32세"


@pytest.mark.parametrize("separator", ["\r", "\n", ".", "!", "?"])
def test_d3_comparison_stays_in_clause(separator):
    text = "나이: 32세" + separator + "더 많았어요."
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert [text[r.start : r.end] for r in results] == ["32세"]


def test_d3_comparison_spacing_bound():
    text = "나이: 5살" + " " * 15 + "더" + " " * 7 + "많았지만 비교입니다."
    assert AgeStatementRecognizer().analyze(text, ["AGE"]) == []


@pytest.mark.parametrize(
    "text",
    [
        "고객 나이: 32세 더 적응이 필요합니다.",
        "고객 나이: 32세 더 적극적인 안내가 필요합니다.",
        "고객 나이: 32세 더 적절한 안내가 필요합니다.",
    ],
)
def test_d4_lexical_collision(text):
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert len(results) == 1
    result = results[0]
    assert 0 <= result.start < result.end <= len(text)
    assert text[result.start : result.end] == "32세"


@pytest.mark.parametrize(
    "predicate",
    [
        "더 적습니다",
        "더 적지만 성인입니다",
        "더 적어서 먼저 입학했습니다",
        "더 적었어요",
        "더 적은 편입니다",
        "더 적게 보입니다",
        "더 적으면 조건이 달라집니다",
        "더 많습니다",
        "더 많았어요",
        "더 많지만 학생입니다",
        "덜 적었겠지요",
        "더 적",
        "더 적, 비교입니다",
        "더 적 다만 비교입니다",
    ],
)
def test_d4_predicate_continuation(predicate):
    assert AgeStatementRecognizer().analyze(f"나이는 5살 {predicate}", ["AGE"]) == []


def test_d4_predicate_boundary_at_spacing_limit():
    text = "고객 나이: 32세" + " " * 15 + "더" + " " * 7 + "적응이 필요합니다."
    results = AgeStatementRecognizer().analyze(text, ["AGE"])
    assert [text[r.start : r.end] for r in results] == ["32세"]
