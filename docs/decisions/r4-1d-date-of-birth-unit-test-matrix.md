# R4-1D — DATE_OF_BIRTH Unit Test Matrix

Status: TEST_MATRIX_FROZEN
Stage: TESTS-BEFORE-IMPLEMENTATION
Entity: DATE_OF_BIRTH
Layer: L3
Baseline HEAD: 6d9165e97182ec0b56cb9d72e518c8bc28ece47e

---

## 1. Authority

This matrix translates the frozen R4-1C DATE_OF_BIRTH behavior
contract into executable unit-test expectations.

It MUST NOT introduce new semantic behavior.

Authoritative common contracts remain:

- `src/privacy_proxy/schemas.py`
- `src/privacy_proxy/contracts/detection.py`

Frozen entity behavior contract:

- `docs/decisions/r4-1c-date-of-birth-behavior-contract.md`

---

## 2. Expected Test File

The entity-owned unit-test file will be:

    tests/unit/test_date_of_birth.py

The runtime implementation file does not yet exist and MUST NOT be
created during R4-1D-B.

Expected implementation file in the later R4-1E stage:

    src/privacy_proxy/l3/date_of_birth_recognizer.py

---

## 3. Producer Contract Matrix

### P01 — exact producer identity

Expected:

    class name = DateOfBirthRecognizer
    producer.name = DateOfBirthRecognizer

### P02 — exact supported entity

Expected:

    supported_entities == ["DATE_OF_BIRTH"]

### P03 — exact language

Expected:

    supported_language == "ko"

### P04 — wrong requested entity

Input entity list examples:

    []
    ["AGE"]
    ["EMAIL_ADDRESS"]

Expected:

    []

No unrelated entity capability is emitted.

---

## 4. Positive Surface Matrix

All fixtures are synthetic.

### POS-ISO-01

Input:

    생년월일 2004-01-02

Expected surface:

    2004-01-02

Expected count:

    1

### POS-COMPACT-01

Input:

    생년월일 20040102

Expected surface:

    20040102

Expected count:

    1

### POS-KO-01

Input:

    생년월일 2004년 1월 2일

Expected surface:

    2004년 1월 2일

Expected count:

    1

### POS-KO-02

Input:

    생년월일은 2004년 01월 02일입니다.

Expected surface:

    2004년 01월 02일

Expected count:

    1

### POS-BIRTHDAY-01

Input:

    생일은 2004-01-02입니다.

Expected surface:

    2004-01-02

Expected count:

    1

### POS-SUFFIX-01

Input:

    2004년 1월 2일생입니다.

Expected surface:

    2004년 1월 2일

Expected count:

    1

---

## 5. Approved Prefix-Relation Matrix

The approved local order is:

    anchor
    -> optional particle
    -> optional horizontal whitespace
    -> optional single delimiter
    -> optional horizontal whitespace
    -> date

Positive examples include:

    생년월일 2004-01-02
    생년월일: 2004-01-02
    생년월일 = 20040102
    생년월일은 2004-01-02
    생년월일은: 2004-01-02
    생일은 2004년 1월 2일

Each example MUST emit exactly the date surface.

---

## 6. Bare-Date Rejection Matrix

The following MUST NOT emit:

    2004-01-02
    20040102
    2004년 1월 2일

Expected:

    []

---

## 7. Non-Birth Semantic Rejection Matrix

The following MUST NOT emit DATE_OF_BIRTH:

    주문일은 2004-01-02입니다.
    접수일은 2004-01-02입니다.
    계약일은 2004-01-02입니다.
    배송일은 2004-01-02입니다.

Expected:

    []

---

## 8. Unrelated Lexical Material Matrix

These MUST NOT use a distant birth word as evidence:

    생년월일이 아니라 주문일은 2004-01-02입니다.
    생년월일 관련 문의입니다. 주문일은 2004-01-02입니다.

Expected:

    []

Document-wide birth-word inference is forbidden.

---

## 9. Distance Matrix

Raw anchor distance is measured from the end of the approved
prefix anchor to the start of the date surface.

### DIST-01

Distance:

    1

Expected:

    EMIT

### DIST-15

Distance:

    15

Expected:

    EMIT

### DIST-16

Distance:

    16

Expected:

    NO EMIT

### DIST-00

Distance:

    0

Example:

    생년월일2004-01-02

Expected:

    NO EMIT

---

## 10. Horizontal Whitespace Matrix

Approved horizontal whitespace:

    ASCII SPACE U+0020
    TAB U+0009

Positive cases MUST cover both.

CR and LF are not horizontal relation whitespace.

---

## 11. Delimiter / Particle Matrix

Approved particles:

    은
    는
    이

Approved delimiters:

    :
    =

At most one approved particle and at most one approved delimiter
may occur.

Repeated particle or delimiter examples MUST be rejected.

Examples:

    생년월일은은 2004-01-02
    생년월일:: 2004-01-02
    생년월일== 2004-01-02

Expected:

    []

---

## 12. Clause Boundary Matrix

Hard clause boundaries:

    CR
    LF
    .
    !
    ?

For each separator:

    생년월일<BOUNDARY>2004-01-02

Expected:

    []

Birth evidence MUST NOT cross the boundary.

---

## 13. Gregorian Calendar Validation Matrix

### CAL-VALID-LEAP

Input:

    생년월일 2004-02-29

Expected:

    EMIT

### CAL-INVALID-DAY

Input:

    생년월일 2004-02-30

Expected:

    []

### CAL-INVALID-LEAP

Input:

    생년월일 2003-02-29

Expected:

    []

### CAL-INVALID-MONTH

Input:

    생년월일 2004-13-01

Expected:

    []

### CAL-INVALID-DAY-ZERO

Input:

    생년월일 2004-01-00

Expected:

    []

Calendar rejection is semantic NO EMIT.

---

## 14. Future-Date / Clock Matrix

R4-1C freezes:

    evaluation date = UTC calendar date at recognizer evaluation time

The DATE_OF_BIRTH implementation MUST expose an implementation-local,
replaceable clock boundary.

Selected minimal implementation seam for R4-1E:

    _utc_today() -> date

This helper is NOT a public contract.

It exists only to provide deterministic evaluation-date behavior and
testability without expanding the recognizer constructor API.

Unit tests will monkeypatch this module-local helper.

### CLOCK-01 — past

Frozen evaluation date:

    2026-10-08

DOB:

    2004-01-02

Expected:

    EMIT

### CLOCK-02 — equal date

Frozen evaluation date:

    2026-10-08

DOB:

    2026-10-08

Expected:

    EMIT

provided all other DOB semantics pass.

### CLOCK-03 — future

Frozen evaluation date:

    2026-10-08

DOB:

    2026-10-09

Expected:

    []

Unit tests MUST NOT depend on the machine wall clock.

---

## 15. Partial-Date Rejection Matrix

Unsupported surfaces include:

    2004년
    1월 2일
    2004-01

Even with a valid birth anchor:

    생년월일 2004년
    생년월일 1월 2일
    생년월일 2004-01

Expected:

    []

---

## 16. Numeric Boundary Matrix

Compact YYYYMMDD MUST NOT be extracted from a longer digit sequence.

Positive:

    생년월일 20040102

Expected surface:

    20040102

Negative examples:

    생년월일 1200401023
    생년월일 99120040102123

Expected:

    []

Equivalent digit-boundary protection applies to ISO numeric surfaces.

---

## 17. Korean Attached-Suffix Regression Matrix

The following remains valid:

    생년월일은 2004-01-02입니다.

Expected:

    one DATE_OF_BIRTH result

Expected surface:

    2004-01-02

A Hangul character immediately after the numeric date MUST NOT reproduce
the built-in Presidio DateRecognizer word-boundary failure discovered
during R4-1B.

---

## 18. Suffix Relation Matrix

Approved:

    2004년 1월 2일생입니다.

Expected:

    2004년 1월 2일

Not approved in v0.1:

    2004-01-02생입니다.
    20040102생입니다.

Expected:

    []

The evidence character `생` is excluded from the emitted span.

---

## 19. Exact Span Matrix

For every emitted result:

    0 <= start < end <= len(text)

and:

    text[result.start:result.end] == expected_surface

Anchor, particle, delimiter, copula, punctuation, and surrounding
whitespace MUST NOT be included.

---

## 20. Duplicate Result Matrix

If one date span can be supported through more than one internal
evidence path:

    entity_type + start + end

MUST occur at most once.

No duplicate RecognizerResult is permitted for the same DATE_OF_BIRTH
raw span.

---

## 21. Recognition Metadata Matrix

Every emitted `RecognizerResult` MUST contain:

    RecognizerResult.RECOGNIZER_NAME_KEY
    RecognizerResult.RECOGNIZER_IDENTIFIER_KEY

Expected values:

    recognizer_name == producer.name
    recognizer_identifier == producer.id

This preserves compatibility with the existing provenance resolver.

---

## 22. Internal Score Boundary

The exact internal `RecognizerResult.score` value is NOT frozen.

Unit tests MUST NOT assert one specific numeric score.

Tests may verify only that producer API output remains structurally valid.

The internal score MUST NOT be interpreted as canonical confidence or
DetectionTier evidence.

---

## 23. Timeout / Failure Matrix

The producer MUST use the existing L3 `protect_callable` boundary.

A dependency/regex timeout MUST remain observable through the existing
L3 timeout mechanism.

Expected timeout class:

    L3DependencyTimeoutError

An unexpected runtime exception MUST NOT be converted into:

    []

or another successful semantic rejection.

No raw synthetic date value needs to be interpolated into failure
messages.

---

## 24. Synthetic Fixture Rule

All unit-test DOB values are synthetic.

No actual customer, student, employee, patient, or other real person's
birth date may be copied into the test suite.

---

## 25. Existing Regression Boundary

R4-1D MUST NOT modify existing integration tests which currently classify
DATE_OF_BIRTH as unsupported.

In particular, R4-1D does not yet change:

    tests/integration/test_age_runtime.py
    tests/integration/test_age_group_runtime.py
    tests/unit/test_l3.py
    tests/unit/test_phone.py

Capability migration belongs to R4-1F after the producer implementation
and entity-owned unit evidence exist.

---

## 26. R4-1D-C Authorization

After this matrix is verified:

    tests/unit/test_date_of_birth.py

may be authored before implementation.

The test file MUST encode this matrix.

The implementation file:

    src/privacy_proxy/l3/date_of_birth_recognizer.py

MUST still not be created until the R4-1D test candidate exists.

The initial RED state may be a module import/collection failure because
the implementation module intentionally does not yet exist.

That RED state MUST NOT be "fixed" by weakening or skipping tests.

Next stage:

    R4-1D-C
    DATE_OF_BIRTH Unit Test Candidate Authoring
