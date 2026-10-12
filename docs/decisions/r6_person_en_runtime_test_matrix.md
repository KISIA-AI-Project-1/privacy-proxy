# R6 PERSON_EN Runtime Test Matrix

Status: R6-S2B ADJUDICATED / RED-TEST INPUT

Baseline:

`1623a94c98b715fd4bf33f2d27aeefcb6a695567`

---

## 1. Hard Contract Cases

| ID | Class | Input / Condition | Expected Canonical Behavior |
|---|---|---|---|
| P01 | BASIC | `John Smith contacted support.` | emit `PERSON_EN=John Smith` |
| P02 | CONTEXT | `The customer is Alice Brown.` | emit `PERSON_EN=Alice Brown` |
| P03 | TITLE | `Dr. John Smith contacted support.` | emit `John Smith`; exclude `Dr.` |
| B01 | ASCII_POSSESSIVE | `John Smith's package has shipped.` | emit `John Smith`; exclude terminal `'s` |
| B02 | UNICODE_POSSESSIVE | `John Smith’s package has shipped.` | emit `John Smith`; exclude terminal `’s` |
| B03 | HYPHEN | `Mary-Jane Watson requested a refund.` | preserve full `Mary-Jane Watson` |
| B04 | INTERNAL_APOSTROPHE | `Patrick O'Neil requested support.` | preserve full `Patrick O'Neil` |
| B05 | MIDDLE_INITIAL | `John A. Smith requested support.` | preserve full `John A. Smith` |
| O01 | KOREAN_ONLY | `김민수...` | no `PERSON_EN` |
| O02 | MIXED_SUFFIX | `John Smith와 김민수...` | emit only `John Smith` |
| O03 | ROMANIZED_KOREAN | `Minsoo Kim contacted support.` | emit `PERSON_EN=Minsoo Kim` |
| O04 | KOREAN_LATIN_CONTEXT | `김민수 contacted support.` | no `PERSON_EN` |
| N01 | ORG_NEGATIVE | `Microsoft released an update.` | no `PERSON_EN` |
| N02 | LOCATION_NEGATIVE | `Seattle has heavy rain today.` | no `PERSON_EN` |
| N03 | GENERIC_NEGATIVE | `The order number is 12345678.` | no `PERSON_EN` |

---

## 2. Schema Contract Cases

| ID | Requirement | Expected |
|---|---|---|
| S01 | entity type | `PERSON_EN` |
| S02 | confidence | `None` |
| S03 | tier | `DetectionTier.MODEL` |
| S04 | source | `PersonEnRecognizer` |
| S05 | original value | exact refined raw slice |
| S06 | normalized | equal to `original_value` |
| S07 | span invariant | `raw_prompt[start_idx:end_idx] == original_value` |
| S08 | upstream score | must not populate canonical confidence |

---

## 3. Boundary Refinement Cases

### BR01 - ASCII possessive

Upstream candidate:

`John Smith's`

Canonical:

`John Smith`

Expected end-index delta:

`-2`

### BR02 - Unicode possessive

Upstream candidate:

`John Smith’s`

Canonical:

`John Smith`

Expected end-index delta:

`-2`

### BR03 - Approved Korean postposition

Upstream candidate:

`John Smith와`

Canonical:

`John Smith`

Expected end-index delta:

`-1`

The implementation must remove only an explicitly approved Korean postposition.

Suffix matching must use longest-match-first semantics.

RED coverage must include at least:

- `John Smith와`
- `John Smith에게`
- `John Smith으로`

Generic trailing Hangul stripping is prohibited.

### BR03-N - Non-postposition Hangul negative

Candidate:

`John김민수`

Expected:

do not convert the candidate to `John` by trimming arbitrary Hangul.

If Hangul remains after approved refinement, do not emit the candidate as `PERSON_EN`.

### BR04 - Internal apostrophe preservation

Upstream candidate:

`Patrick O'Neil`

Canonical:

`Patrick O'Neil`

Expected end-index delta:

`0`

---

## 4. Ownership Cases

| ID | Candidate | Expected |
|---|---|---|
| OW01 | Latin-script person | eligible for `PERSON_EN` |
| OW02 | romanized Korean name | eligible for `PERSON_EN` |
| OW03 | Hangul-only name | not emitted by `PERSON_EN` |
| OW04 | Latin name with absorbed approved Korean postposition | trim approved postposition then evaluate |
| OW05 | Hangul remains after refinement | reject as `PERSON_EN` |

---

## 5. Observational / Non-Hard Cases

The following discovery observations must not become deterministic heuristics:

| ID | Input | Discovery Observation |
|---|---|---|
| A01 | `Jordan called yesterday.` | upstream PERSON not emitted |
| A02 | `Taylor requested a refund.` | upstream PERSON emitted |

These cases may be retained as model-behavior observations, but RED tests must not introduce a capitalization fallback to force a result.

---

## 6. Dependency Failure Cases

| ID | Failure | Expected |
|---|---|---|
| F01 | approved model unavailable | fail closed |
| F02 | PERSON producer initialization failure | fail closed |
| F03 | unexpected upstream entity label | do not relabel |
| F04 | invalid refined span | do not emit |
| F05 | final candidate contains Hangul | do not emit as `PERSON_EN` |

---

## 7. Regression Guards

Implementation must demonstrate that PERSON_EN addition does not change previously frozen L3 behavior.

Required regression controls include at least:

- EMAIL_ADDRESS control;
- PHONE_NUMBER existing suite;
- AGE existing suite;
- AGE_GROUP existing suite;
- DATE_OF_BIRTH existing suite;
- LOCATION existing suite;
- canonical schema tests;
- L4 PERSON_KO ownership tests.

---

## 8. RED-Test Construction Order

Recommended RED-test order:

1. canonical refinement unit tests;
2. PersonEnRecognizer producer tests;
3. schema/tier/source tests;
4. service explicit-request tests;
5. mixed-language ownership tests;
6. model failure / fail-closed tests;
7. existing regression suites;
8. default-request integration only after explicit PERSON_EN runtime passes.

No production implementation should be added before the RED tests demonstrate the expected failures.
