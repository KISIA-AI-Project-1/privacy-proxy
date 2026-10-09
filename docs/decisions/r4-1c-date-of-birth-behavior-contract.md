# R4-1C — DATE_OF_BIRTH Behavior Contract

Status: PRE_IMPLEMENTATION_FROZEN<br>
Stage: R4-1D UNIT-TEST AUTHORING AUTHORIZED<br>
Entity: DATE_OF_BIRTH<br>
Layer: L3
Baseline HEAD: 6d9165e97182ec0b56cb9d72e518c8bc28ece47e

---

## 1. Authority

The authoritative common contracts are:

- `src/privacy_proxy/schemas.py`
- `src/privacy_proxy/contracts/detection.py`

DATE_OF_BIRTH runtime code MUST conform to these contracts.

This entity-local behavior contract does not authorize changes to either
authoritative common contract.

---

## 2. Discovery Basis

R4-1B / R4-1B2 / R4-1B3 established that Presidio `DateRecognizer`
is not an acceptable DATE_OF_BIRTH producer.

Direct reuse is rejected because:

1. it detects generic `DATE_TIME`;
2. birth semantics are not required;
3. relabel-only reuse converts generic dates into `DATE_OF_BIRTH`;
4. built-in word-boundary behavior is incompatible with ordinary
   Korean suffix attachment;
5. required `YYYYMMDD` and Korean-native date surfaces are absent;
6. real Gregorian calendar validity is not enforced.

Selected implementation direction:

    DateOfBirthRecognizer

Base-class direction:

    EntityRecognizer

---

## 3. Canonical Detection Output

DATE_OF_BIRTH output MUST use the canonical `DetectedPII` contract.

Required behavior:

- `entity_type = DATE_OF_BIRTH`
- `confidence = None`
- `source = DateOfBirthRecognizer`
- `tier = DetectionTier.RULE_ANCHORED`
- `original_value = raw_prompt[start_idx:end_idx]`
- `normalized = original_value`
- offsets are zero-based and half-open
- the canonical raw coordinate system is preserved

Required invariant:

    raw_prompt[start_idx:end_idx] == original_value

No DATE_OF_BIRTH-specific DTO is introduced.

No common schema change is authorized.

---

## 4. Supported Date Surfaces — v0.1

The following full-date surfaces MUST be supported in v0.1.

Surface grammar is intentionally narrow:

- ISO uses four year digits, two month digits, and two day digits.
- Compact uses exactly eight digits: `YYYYMMDD`.
- Korean native uses a four-digit year and one- or two-digit month/day.

### 4.1 ISO

Format:

    YYYY-MM-DD

Example:

    2004-01-02

### 4.2 Compact

Format:

    YYYYMMDD

Example:

    20040102

### 4.3 Korean Native

Format:

    YYYY년 M월 D일

Examples:

    2004년 1월 2일
    2004년 01월 02일

Partial dates are not part of v0.1.

Examples outside v0.1:

    2004년
    1월 2일
    2004-01

---

## 5. Birth Semantic Requirement

A syntactically valid date alone MUST NOT emit `DATE_OF_BIRTH`.

Birth-semantic evidence is required.

Approved prefix anchors:

    생년월일
    생일

Approved Korean suffix relation:

    YYYY년 M월 D일생

The semantic anchor is evidence only.

The emitted PII span contains the date surface itself,
not the anchor, particle, copula, or surrounding sentence.

Example:

    생년월일은 2004-01-02입니다.
               └────────┘
               DATE_OF_BIRTH

---

## 6. Bare Date Policy

Bare dates MUST NOT emit `DATE_OF_BIRTH`.

Examples:

    2004-01-02
    20040102
    2004년 1월 2일

Without approved birth-semantic evidence:

    NO EMIT

Reason:

A bare date may represent an order date, receipt date,
contract date, delivery date, or another non-birth event.

---

## 7. Negative Semantic Surface

The following date relations MUST NOT emit `DATE_OF_BIRTH`:

    주문일
    접수일
    계약일
    배송일

Examples:

    주문일은 2004-01-02입니다.
    접수일은 2004-01-02입니다.
    계약일은 2004-01-02입니다.
    배송일은 2004-01-02입니다.

Expected result:

    NO DATE_OF_BIRTH

The recognizer MUST NOT infer DATE_OF_BIRTH merely because
a valid date pattern is present.

---

## 8. Anchor Relation Boundary

Birth semantics MUST be established through an approved local structural
relation.

### 8.1 Approved Prefix Anchors

The only approved prefix anchors in v0.1 are:

    생년월일
    생일

No synonym expansion is authorized in v0.1.

### 8.2 Approved Prefix Relation

Between an approved prefix anchor and the date surface, v0.1 may contain
only the following local elements:

- optional Korean particle: `은`, `는`, or `이`
- optional separator: `:` or `=`
- horizontal whitespace consisting of SPACE or TAB

No arbitrary lexical material may occur between the anchor and date.

The approved relation order is:

    anchor
    -> optional particle
    -> optional horizontal whitespace
    -> optional single delimiter
    -> optional horizontal whitespace
    -> date

At most one approved particle may occur.

At most one approved delimiter may occur.

Repeated particles or repeated delimiters are rejected.

If no particle and no delimiter are present, at least one horizontal
whitespace character is required so that raw anchor distance is not zero.

Approved examples include:

    생년월일 2004-01-02
    생년월일: 2004-01-02
    생년월일 = 20040102
    생년월일은 2004-01-02
    생년월일은: 2004-01-02
    생일은 2004년 1월 2일

The relation MUST remain local.

Raw prefix-anchor distance is measured from the end of the approved
anchor to the beginning of the emitted date surface.

The v0.1 distance contract is:

    minimum raw anchor distance = 1 Python character
    maximum raw anchor distance = 15 Python characters inclusive

Distance 0 is rejected.

This preserves the existing bounded L3 anchor/gap precedent and prevents
an unbounded horizontal-space relation.

Only ASCII SPACE U+0020 and TAB U+0009 are recognized as horizontal
whitespace.

The total raw anchor distance remains bounded by 15 characters even when
a particle or delimiter is present.

CR and LF are not approved relation characters in v0.1.

Therefore the following does not establish an approved prefix relation:

    생년월일은
    2004-01-02

### 8.3 Clause Boundary

Birth evidence MUST NOT cross a clause or unrelated lexical phrase.

The following are hard clause boundaries in v0.1:

    CR
    LF
    .
    !
    ?

An approved birth anchor before one of these boundaries cannot provide
semantic evidence for a date after that boundary.

Examples which MUST NOT elevate the date to DATE_OF_BIRTH:

    생년월일이 아니라 주문일은 2004-01-02입니다.
    생년월일 관련 문의입니다. 주문일은 2004-01-02입니다.

The implementation MUST NOT perform document-wide
"birth word exists somewhere" inference.

### 8.4 Approved Suffix Relation

The approved suffix relation in v0.1 is limited to the Korean-native
full-date surface immediately followed by `생`.

Example:

    2004년 1월 2일생입니다.

The emitted span is:

    2004년 1월 2일

The suffix evidence character `생` is not part of the emitted PII span.

The following suffix forms are not approved in v0.1:

    2004-01-02생
    20040102생

### 8.5 Numeric Surface Boundary

A supported date surface MUST NOT be extracted from inside a longer
digit sequence.

In particular, compact `YYYYMMDD` requires non-digit boundaries on both
sides of the eight-digit surface.

Example:

    생년월일 20040102

may emit DATE_OF_BIRTH.

But an eight-digit substring embedded inside a longer numeric identifier
MUST NOT be extracted as DATE_OF_BIRTH.

Equivalent digit-boundary protection applies to numeric ISO candidates.

### 8.6 Duplicate Result Rule

For one `DATE_OF_BIRTH` entity with the same zero-based half-open
`start_idx` and `end_idx`, the recognizer MUST emit at most one
`RecognizerResult`.

Multiple semantic evidence paths MUST NOT create duplicate detections
for the same raw date span.

---

## 9. Calendar Validity

A date-pattern match is insufficient.

The extracted year, month, and day MUST form a real Gregorian date.

Examples:

    2004-02-29
        VALID

    2004-02-30
        INVALID

    2003-02-29
        INVALID

Invalid calendar dates:

    NO EMIT

Calendar validity is a deterministic sub-check.

It does not make the complete DATE_OF_BIRTH detection
`DETERMINISTIC`, because birth-semantic evidence is still required.

Therefore the final detection tier remains:

    RULE_ANCHORED

---

## 10. Future-Date Policy

A DATE_OF_BIRTH value later than the evaluation date MUST NOT emit.

For v0.1:

    evaluation date = UTC calendar date at recognizer evaluation time

The implementation MUST use an explicit clock boundary so unit tests can
freeze or replace the evaluation date without depending on the machine's
wall clock.

Expected result for a date later than the evaluation date:

    NO EMIT

A date equal to the evaluation date is not rejected by the future-date
rule if all other DATE_OF_BIRTH requirements pass.

v0.1 does not introduce an arbitrary minimum birth year.

No age-range or demographic policy is inferred solely for
DATE_OF_BIRTH detection.

---

## 11. Span Contract

Only the date surface is emitted.

Example:

    생년월일은 2004-01-02입니다.

    original_value:
    2004-01-02

Example:

    생년월일은 2004년 1월 2일입니다.

    original_value:
    2004년 1월 2일

The following MUST NOT be included in the emitted span:

- birth anchor
- Korean particle
- sentence-ending copula
- punctuation outside the date
- unrelated surrounding text

Ordinary Korean text immediately following the approved date surface
MUST NOT invalidate an otherwise valid detection merely because the
following character is Hangul.

For example:

    생년월일은 2004-01-02입니다.

remains a supported positive surface and emits only:

    2004-01-02

The canonical invariant remains:

    raw_prompt[start_idx:end_idx] == original_value

---

## 12. Normalization Policy — v0.1

v0.1 does not introduce producer-specific canonical ISO conversion.

Required behavior:

    normalized = original_value

Examples:

    original_value = "2004-01-02"
    normalized     = "2004-01-02"

and:

    original_value = "2004년 1월 2일"
    normalized     = "2004년 1월 2일"

A future ISO-normalization requirement must be handled as a
separate reviewed behavior change.

---

## 13. Source / Provenance

The DATE_OF_BIRTH producer identity is:

    DateOfBirthRecognizer

The producer capability is exactly:

    supported_entities = ["DATE_OF_BIRTH"]
    supported_language = "ko"

The producer MUST NOT advertise generic DATE_TIME or any unrelated
entity capability.

The canonical output source MUST reflect the verified producer.

Each emitted `RecognizerResult` MUST retain sufficient recognizer
identity metadata for the existing provenance resolver to verify the
actual `DateOfBirthRecognizer` producer.

No score-based or label-only provenance inference is permitted.

---

## 14. Confidence

L3 canonical confidence behavior is preserved.

    confidence = None

No DATE_OF_BIRTH-specific numeric confidence model is introduced.

Any internal Presidio `RecognizerResult.score` required by the producer
API is implementation-local evidence only.

Its numeric value MUST NOT be:

- copied into canonical `confidence`;
- used to select `DetectionTier`;
- treated as proof of birth semantics.

Unit tests MUST NOT make the exact internal score part of the semantic
behavior contract unless a later reviewed decision explicitly freezes it.

---

## 15. Detection Tier

DATE_OF_BIRTH tier for v0.1:

    RULE_ANCHORED

Rationale:

    date surface
    +
    calendar validity
    +
    birth-semantic relation

The deterministic calendar-validity sub-check alone is not sufficient
to classify the entire detection as `DETERMINISTIC`.

---

## 16. Failure Semantics

Expected semantic rejection:

    NO EMIT

Examples:

- bare date
- non-birth date context
- invalid Gregorian date
- future date
- unsupported partial date

Unexpected runtime failures MUST remain observable.

Runtime exceptions MUST NOT be converted into successful
safe rejection merely to make a test pass.

Existing L3 timeout and fail-closed dependency behavior MUST be
preserved.

---

## 17. Non-Goals — v0.1

The following are not approved by this contract:

- generic DATE_TIME detection
- partial birth dates
- inferred DOB from AGE
- inferred DOB from KR_RRN
- OCR/image date extraction
- adversarial whitespace evasion
- homoglyph handling
- arbitrary document-wide semantic inference
- producer-specific ISO normalization

---

## 18. Pre-Implementation Freeze

R4-1C status:

    PASS

Behavior contract status:

    PRE_IMPLEMENTATION_FROZEN

The semantic expectations in Sections 1 through 17 are frozen for
R4-1D test authoring.

R4-1D may encode these expectations as executable tests but MUST NOT:

- widen supported surfaces;
- add new anchors;
- alter distance or clause boundaries;
- change calendar-validity semantics;
- change span semantics;
- change normalization;
- change source or tier semantics;
- weaken semantic rejection;
- convert runtime failures into NO EMIT.

If an implementation-relevant contradiction is discovered, R4-1D MUST
stop and return to R4-1C review.

This is not the final runtime freeze.

`FINAL_FROZEN` remains reserved for post-implementation,
post-regression verification.

---

## 19. Implementation Authorization Boundary

This R4-1C document defines expected behavior before implementation.

It does NOT yet authorize:

- registry registration
- tier-mapping modification
- service capability expansion
- implementation commit
- push
- merge

Next stage:

    R4-1D
    DATE_OF_BIRTH Unit Tests First

The tests MUST encode this behavior contract before
`DateOfBirthRecognizer` runtime implementation is added.

R4-1D tests may translate this contract into executable expectations,
but MUST NOT invent new semantic behavior.

If an implementation-relevant expectation remains ambiguous during
R4-1D, test authoring MUST stop and this R4-1C contract must be reviewed
again rather than resolving the ambiguity inside test code.
