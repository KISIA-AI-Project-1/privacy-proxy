"""H2 pre-registration A-W / AA: synthetic fixtures, independent raw offsets.

IDs retain DETECTED_EXPECTED, SEMANTIC_REJECTION and DEFERRED_SCOPE separately.
Expected offsets are prefix lengths, never detector outputs or substring search.
"""

from dataclasses import dataclass

import pytest
from presidio_analyzer import RecognizerResult

from privacy_proxy.l3.age_group_recognizer import AgeGroupStatementRecognizer


@dataclass(frozen=True)
class Case:
    case_id: str
    raw: str
    expected: tuple[tuple[int, int, str], ...] = ()
    outcome: str = "SEMANTIC_REJECTION"


def positive(case_id, prefix, value, suffix=""):
    return Case(
        case_id,
        prefix + value + suffix,
        ((len(prefix), len(prefix) + len(value), value),),
        "DETECTED_EXPECTED",
    )


def person(case_id, value):
    return positive(case_id, "고객은 ", value, "입니다.")


def rejected(case_id, raw):
    return Case(case_id, raw)


def deferred(case_id, value):
    return Case(case_id, "고객은 " + value + "입니다.", outcome="DEFERRED_SCOPE")


def horizontal(kind, n):
    return {"S": " " * n, "T": "\t" * n, "M": (" \t" * n)[:n]}[kind]


PERSONAL = (
    "저는",
    "제가",
    "나는",
    "내가",
    "고객은",
    "고객이",
    "고객님은",
    "고객님이",
    "본인은",
    "본인이",
)
LABELS = ("나이", "나이는", "나이가", "연령", "연령은", "연령이", "연령대", "연령대는", "연령대가")
COPULAS = ("입니다", "이에요", "예요", "이다", "이고", "이며")
INTERMEDIATE = ("현재", "올해", "지금")
REFINED = ("초반", "중반", "후반")
BOUNDARIES = ("\r", "\n", "\r\n", ".", "!", "?")
CASES = []

for decade in range(10, 100, 10):
    value = f"{decade}대"
    CASES += [person(f"A-01-{decade}", value), positive(f"A-02-{decade}", "연령대: ", value)]
    for refinement in REFINED:
        CASES.append(person(f"B-01-{decade}-{refinement}", value + " " + refinement))

for i, value in enumerate(("30대초반", "30대  초반", "30 대 초반", "30\t대\t초반")):
    CASES.append(person(f"B-02-{i}", value))

for a in PERSONAL:
    CASES.append(positive(f"F-01-{a}", a + " ", "30대", "입니다."))
for a in LABELS:
    CASES.append(positive(f"G-01-{a}", a + " ", "30대"))
for a in ("제", "내", "고객", "고객님", "본인"):
    CASES.append(positive(f"E-01-{a}", a + " 연령대: ", "30대"))
for w in INTERMEDIATE:
    CASES += [
        positive(f"K-01-{w}", "고객은 " + w + " ", "30대", "입니다."),
        positive(f"K-02-{w}", "연령대: " + w + " ", "30대"),
        positive(f"K-03-{w}", "연령대 " + w + " ", "30대"),
    ]
for c in COPULAS:
    CASES += [
        positive(f"L-01-{c}", "고객은 ", "30대", c + "."),
        positive(f"L-02-{c}", "연령대: ", "30대", c + "."),
        positive(f"B-06-{c}", "고객은 ", "30대 초반", c + "."),
    ]
CASES += [
    positive("L-03", "연령대:", "30대"),
    positive("B-05", "연령대: ", "30대 초반"),
    positive("B-07", "고객은 ", "30대 초반", " 입니다."),
    person("B-08", "30대 초반"),
]

for kind in ("S", "T", "M"):
    for n in (0, 1, 14, 15, 16):
        gap = horizontal(kind, n)
        for a, suffix, name in (("고객은", "입니다.", "personal"), ("연령대", "", "label")):
            key = f"H-{name}-{kind}-{n}"
            if 1 <= n <= 15:
                CASES.append(positive(key, a + gap, "30대", suffix))
            else:
                CASES.append(rejected(key, a + gap + "30대" + suffix))
    for n in (0, 1, 15, 16):
        gap = horizontal(kind, n)
        key = f"I-digits-{kind}-{n}"
        value = "30" + gap + "대"
        CASES.append(
            person(key, value) if n <= 15 else rejected(key, "고객은 " + value + "입니다.")
        )
        for refinement in REFINED:
            key = f"B-refined-{kind}-{n}-{refinement}"
            value = "30대" + gap + refinement
            CASES.append(
                person(key, value) if n <= 15 else rejected(key, "고객은 " + value + "입니다.")
            )
        for prefix in ("고객은 ", "연령대: "):
            key = f"I-copula-{prefix}-{kind}-{n}"
            raw = prefix + "30대" + gap + "입니다."
            CASES.append(
                positive(key, prefix, "30대", gap + "입니다.") if n <= 15 else rejected(key, raw)
            )
    for n in (1, 15):
        CASES.append(
            rejected(f"I-number-{kind}-{n}", "고객은 3" + horizontal(kind, n) + "0대입니다.")
        )

for n in (10, 11, 12):
    prefix = "연령대:" + " " * n + "현재 "
    CASES.append(
        positive(f"H-total-label-{n}", prefix, "30대")
        if n <= 11
        else rejected(f"H-total-label-{n}", prefix + "30대")
    )
for n in (11, 12, 13):
    prefix = "고객은" + " " * n + "현재 "
    CASES.append(
        positive(f"H-total-person-{n}", prefix, "30대", "입니다.")
        if n <= 12
        else rejected(f"H-total-person-{n}", prefix + "30대입니다.")
    )

for i, delim in enumerate((":", "\uff1a", "=")):
    CASES += [
        positive(f"J-01-{i}", "연령대" + delim, "30대"),
        positive(f"J-02-{i}", "연령대 " + delim + " ", "30대"),
        rejected(f"J-05-{i}", "고객은" + delim + " 30대입니다."),
    ]
CASES.append(positive("J-03", "연령대 ", "30대"))
for i, delim in enumerate(("::", "\uff1a\uff1a", "==", ":=", "=\uff1a")):
    CASES.append(rejected(f"J-04-{i}", "연령대" + delim + "30대"))
for w in ("현재 현재", "현재 올해", "지금 올해", "현재올해"):
    CASES.append(rejected(f"K-04-{w}", "고객은 " + w + " 30대입니다."))
for w in ("최근", "아마"):
    for prefix in ("고객은 ", "연령대: "):
        CASES.append(rejected(f"K-05-{prefix}-{w}", prefix + w + " 30대입니다."))
for i, raw in enumerate(("연령대 현재:30대", "연령대현재30대", "연령대:현재30대")):
    CASES.append(rejected(f"K-order-{i}", raw))
for i, b in enumerate(BOUNDARIES):
    CASES += [
        rejected(f"M-01-{i}", "연령대" + b + "30대"),
        rejected(f"M-02-{i}", "고객은 30" + b + "대입니다."),
        rejected(f"M-03-{i}", "고객은 30대" + b + "초반입니다."),
        positive(f"M-04-{i}", "연령대" + b + "고객은 ", "30대", "입니다."),
    ]
for b in (",", ";"):
    CASES.append(rejected(f"M-05-{b}", "연령대" + b + "30대"))

for value in ("25대", "020대", "00대", "-20대", "+20대", "20.5대", "2 0대"):
    CASES.append(rejected(f"C-01-{value}", "고객은 " + value + "입니다."))
for a in ("저", "제", "나", "내", "고객", "고객님", "본인"):
    CASES.append(rejected(f"E-02-{a}", a + " 30대입니다."))
for a in ("사용자는", "직원은", "민수는", "제는", "저은", "고객는", "본인가"):
    CASES.append(rejected(f"E-F-invalid-{a}", a + " 30대입니다."))
for a in ("평균연령대", "제품연령대", "연령대별"):
    CASES.append(rejected(f"G-02-{a}", a + " 30대"))
NEGATIVES = {
    "N": ("고객은 30대인가요?", "고객은 30대입니다?", "연령대: 30대인가요?", "연령대: 30대?"),
    "O": ("고객은 30대가 아닙니다.", "연령대: 30대가 아님", "고객은 30대 초반이 아닙니다."),
    "P": ("고객이 30대이면 할인됩니다.", "연령대: 30대인 경우"),
    "Q": (
        "가입 대상은 30대입니다.",
        "권장 연령대: 30대",
        "성인 대상 서비스입니다.",
        "성인만 이용 가능합니다.",
        "미성년자는 가입할 수 없습니다.",
        "30대 고객에게 추천합니다.",
        "20대 상품",
        "20대 추천",
    ),
    "R": ("20대 고객 비중", "고객 연령대별 비중: 20대", "30대가 많이 구매했습니다."),
    "S": tuple("연령대: " + v for v in ("20~30대", "20대~30대", "20대-30대", "20대부터 30대까지"))
    + tuple("연령대: 30대" + s for s in (" 이상", " 이하", " 미만", " 초과", "부터", "까지")),
    "T": (
        *(
            "고객은 " + v + "입니다."
            for v in ("약 30대", "대략 30대", "30대 정도", "30대 전후", "30대쯤")
        ),
        "고객은 30대처럼 보입니다.",
    ),
    "U": ("고객은 30대보다 젊습니다.", "연령대: 30대보다 높음"),
    "V": (
        "차량 20대",
        "제20대",
        "20대형",
        "상품코드: SKU20대X",
        "연령대: SKU20대X",
        "고객은 30대형입니다.",
        "고객은 30대 초반부입니다.",
    ),
    "W": ("연령대: 020대", "연령대: 20대~30대", "연령대: 30대 이상"),
    "BARE": ("30대", "30대입니다", "30대 초반입니다", "고객은 30대"),
}
for category, raws in NEGATIVES.items():
    for i, raw in enumerate(raws):
        CASES.append(rejected(f"{category}-{i}", raw))
for c in ("였습니다", "이네요", "입니다만"):
    for prefix in ("고객은 ", "연령대: "):
        CASES.append(rejected(f"L-05-{prefix}-{c}", prefix + "30대" + c))

for value in (
    "0대",
    "100대",
    "110대",
    "120대",
    "\uff12\uff10대",
    "30대 초",
    "30대 초중반",
    "30대 중후반",
    "성인",
    "미성년자",
    "청소년",
    "아동",
    "어린이",
    "중장년층",
    "노년층",
    "고령자",
    "노인",
):
    CASES.append(deferred(f"D-{value}", value))
for i, ws in enumerate(("\u00a0", "\u3000", "\u2009")):
    for j, raw in enumerate(
        (
            "고객은 30" + ws + "대입니다.",
            "고객은 30대" + ws + "초반입니다.",
            "고객은" + ws + "30대입니다.",
        )
    ):
        CASES.append(Case(f"D-unicode-{i}-{j}", raw, outcome="DEFERRED_SCOPE"))
for value in ("30대 초중반", "30대 중후반"):
    CASES.append(Case(f"W-04-{value}", "연령대: " + value, outcome="DEFERRED_SCOPE"))

CASES += [
    positive("LOCAL-01", "가입 대상은 30대입니다. 고객은 ", "20대", "입니다."),
    positive("LOCAL-02", "고객은 ", "20대", "입니다. 30대 상품을 추천합니다."),
    positive("LOCAL-03", "권장 연령대: 30대, 고객 연령대: ", "40대"),
    positive("LOCAL-04", "고객은 ", "30대", "입니다. 연령대: 40대?"),
    positive("LOCAL-05", "연령대: 30대 정도, 고객 연령대: ", "40대"),
    positive("AA-01", "ASCII. 연령대: ", "30대"),
    positive("AA-02", "한글 안내. 연령대: ", "30대"),
    positive("AA-03", "😀. 연령대: ", "30대"),
    person("AA-04", "30\t대"),
    person("AA-05", "30대  초반"),
]
REPEATED = "고객은 30대입니다. 고객은 30대입니다."
REPEATED_START = len("고객은 30대입니다. 고객은 ")
CASES += [
    Case(
        "X-01",
        REPEATED,
        ((4, 7, "30대"), (REPEATED_START, REPEATED_START + 3, "30대")),
        "DETECTED_EXPECTED",
    ),
    Case(
        "Y-01",
        "연령대: 20대. 고객은 40대 후반입니다.",
        (
            (5, 8, "20대"),
            (
                len("연령대: 20대. 고객은 "),
                len("연령대: 20대. 고객은 ") + len("40대 후반"),
                "40대 후반",
            ),
        ),
        "DETECTED_EXPECTED",
    ),
]


def test_preregistered_case_ids_and_outcomes():
    assert len({c.case_id for c in CASES}) == len(CASES)
    assert {c.outcome for c in CASES} == {
        "DETECTED_EXPECTED",
        "SEMANTIC_REJECTION",
        "DEFERRED_SCOPE",
    }


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.case_id + ":" + c.outcome)
def test_h2_semantic_contract(case):
    producer = AgeGroupStatementRecognizer()
    results = producer.analyze(case.raw, ["AGE_GROUP"])
    actual = sorted((r.start, r.end, case.raw[r.start : r.end]) for r in results)
    assert actual == list(case.expected), case.case_id
    for result in results:
        assert isinstance(result, RecognizerResult)
        assert result.entity_type == "AGE_GROUP"
        assert 0 <= result.start < result.end <= len(case.raw)
        assert result.recognition_metadata[RecognizerResult.RECOGNIZER_NAME_KEY] == producer.name
        assert (
            result.recognition_metadata[RecognizerResult.RECOGNIZER_IDENTIFIER_KEY] == producer.id
        )


@pytest.mark.parametrize("entities", [[], ["AGE"], ["EMAIL_ADDRESS"]])
def test_ab03_unrequested_entity(entities):
    assert AgeGroupStatementRecognizer().analyze("고객은 30대입니다.", entities) == []


# H3 regression expectations are local to this unit suite. Integration keeps
# its own literal cases instead of importing this table.
R2_REJECTIONS = [
    pytest.param("연령대: 30대 인가요?", id="R2-F1-question-SEMANTIC_REJECTION"),
    pytest.param("연령대: 30대\t인가요?", id="R2-F1-tab-SEMANTIC_REJECTION"),
    pytest.param("연령대: 30대 초반 인가요?", id="R2-F1-refined-SEMANTIC_REJECTION"),
    pytest.param("연령대: 30대 이면 할인됩니다.", id="R2-F1-condition-SEMANTIC_REJECTION"),
    pytest.param("연령대: 30대 입니다만", id="R2-F1-ending-SEMANTIC_REJECTION"),
    pytest.param("연령대: 30대 초중반인가요?", id="R2-F2-question-DEFERRED_SCOPE"),
    pytest.param("연령대: 30대 중후반이면 할인됩니다.", id="R2-F2-condition-DEFERRED_SCOPE"),
    pytest.param("평균 연령대: 30대", id="R2-F3-statistics-SEMANTIC_REJECTION"),
    pytest.param("추천 대상 고객은 30대입니다.", id="R2-F3-target-SEMANTIC_REJECTION"),
]


@pytest.mark.parametrize("raw", R2_REJECTIONS)
def test_r2_h3_rejections(raw):
    assert AgeGroupStatementRecognizer().analyze(raw, ["AGE_GROUP"]) == []


@pytest.mark.parametrize("invalid", R2_REJECTIONS)
@pytest.mark.parametrize("valid_first", [False, True])
def test_r2_h3_locality(invalid, valid_first):
    if valid_first:
        raw = "고객은 20대입니다. " + invalid
        start = 4
    else:
        prefix = invalid + ". 고객은 "
        raw = prefix + "20대입니다."
        start = len(prefix)
    results = AgeGroupStatementRecognizer().analyze(raw, ["AGE_GROUP"])
    assert [(r.entity_type, r.start, r.end) for r in results] == [("AGE_GROUP", start, start + 3)]
    assert raw[start : start + 3] == "20대"


@pytest.mark.parametrize("value", ["30대", "30대 초반"])
@pytest.mark.parametrize("gap", ["", " ", "\t", " " * 15])
@pytest.mark.parametrize("ending", ["인가요?", "이면 할인됩니다.", "입니다만"])
def test_r2_unapproved_continuation_semantic_rejection(value, gap, ending):
    raw = "연령대: " + value + gap + ending
    assert AgeGroupStatementRecognizer().analyze(raw, ["AGE_GROUP"]) == []


@pytest.mark.parametrize("value", ["30대 초", "30대 초중반", "30대 중후반"])
@pytest.mark.parametrize("ending", ["", "인가요?", "이면 할인됩니다.", "입니다"])
def test_r2_refinement_deferred_scope_never_falls_back(value, ending):
    assert AgeGroupStatementRecognizer().analyze("연령대: " + value + ending, ["AGE_GROUP"]) == []
