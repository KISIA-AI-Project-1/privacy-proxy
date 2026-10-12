# R6 PERSON_EN Runtime Behavior Contract

Status: R6-S2B ADJUDICATED / NOT YET FINAL_FROZEN

Baseline commit:

`1623a94c98b715fd4bf33f2d27aeefcb6a695567`

Authoritative discovery evidence:

`R6-S2A-R SHA256 = 72EB28A8CA2AA68F8B996C2CBD5A99E678DA89C59C07B04311026C8B250B6BFB`

---

## 1. Scope

This contract defines the L3 runtime behavior for `PERSON_EN`.

It does not change the ownership or behavior of `PERSON_KO`.

`PERSON_EN` is an L3-owned entity.

`PERSON_KO` remains an L4-owned entity.

---

## 2. Upstream Capability

The approved upstream capability is:

- Presidio entity: `PERSON`
- Presidio producer: `SpacyRecognizer`
- NLP engine family: spaCy
- spaCy model: `en_core_web_lg`

The upstream `PERSON` label is not exposed as the canonical project entity.

The canonical project entity is always:

`PERSON_EN`

---

## 3. Ownership Semantics

`PERSON_EN` represents person-name surfaces emitted from the approved English/Latin-script PERSON capability.

Ownership is based on the detected surface and runtime boundary, not the person's nationality.

Examples:

- `John Smith` -> `PERSON_EN`
- `Alice Brown` -> `PERSON_EN`
- `Minsoo Kim` -> `PERSON_EN`
- `김민수` -> not emitted by L3 `PERSON_EN`

Korean-script person detection remains the responsibility of L4 `PERSON_KO`.

---

## 4. Canonical Detection Fields

A successful `PERSON_EN` detection must use the canonical detection schema.

Required semantics:

- `entity_type = PERSON_EN`
- `confidence = null`
- `tier = MODEL`
- `source = PersonEnRecognizer`
- `original_value = raw_prompt[start_idx:end_idx]`
- `normalized = original_value`

The numeric Presidio/spaCy model score must not be copied into the canonical L3 `confidence` field.

---

## 5. Raw Coordinate Invariant

Every emitted detection must satisfy:

`raw_prompt[start_idx:end_idx] == original_value`

Canonical boundary refinement is allowed only by adjusting the raw span coordinates and rebinding `original_value` to the resulting raw slice.

The implementation must not create a normalized string that no longer corresponds to the reported raw coordinates.

---

## 6. Upstream-to-Canonical Relabel

An approved upstream result:

`PERSON`

may be transformed into:

`PERSON_EN`

only after all canonical boundary and ownership rules in this contract pass.

Relabeling must preserve raw-coordinate correctness.

---

## 7. Prefix Behavior

The runtime must not expand the upstream span to include titles or honorifics.

Observed approved behavior:

`Dr. John Smith`

must produce the canonical person span:

`John Smith`

and must not include:

`Dr.`

---

## 8. Internal Name Punctuation

Internal punctuation that is part of the detected name is preserved.

Examples:

`Mary-Jane Watson`

remains:

`Mary-Jane Watson`

`Patrick O'Neil`

remains:

`Patrick O'Neil`

`John A. Smith`

remains:

`John A. Smith`

The implementation must not globally strip apostrophes, hyphens, periods, or spaces from inside a person name.

---

## 9. English Possessive Boundary Refinement

The approved upstream model may include an English possessive suffix inside the PERSON span.

ASCII example:

`John Smith's`

must be refined to:

`John Smith`

Unicode example:

`John Smith’s`

must be refined to:

`John Smith`

Only a terminal possessive suffix is removed.

Internal apostrophes such as the apostrophe in:

`Patrick O'Neil`

must remain intact.

---

## 10. Korean Postposition Boundary Refinement

The approved upstream English model may absorb a Korean postposition immediately following a Latin-script person name.

Observed discovery evidence:

`John Smith와 김민수...`

was emitted upstream as:

`John Smith와`

The canonical `PERSON_EN` span must be refined to:

`John Smith`

The implementation must not remove arbitrary trailing Hangul text.

Only an explicitly approved terminal Korean postposition may be removed.

The initial approved suffix set is:

- `은`
- `는`
- `이`
- `가`
- `을`
- `를`
- `와`
- `과`
- `의`
- `에게`
- `께`
- `도`
- `만`
- `로`
- `으로`
- `에서`
- `부터`
- `까지`

Suffix matching must use longest-match-first semantics so that a shorter suffix cannot partially consume a longer approved suffix.

For example:

`John Smith으로`

must match:

`으로`

as the approved suffix rather than attempting to interpret only:

`로`

The canonical end offset must be moved left by the exact raw length of the approved postposition so that the raw-coordinate invariant remains true.

A sequence such as:

`John김민수`

must not be converted to:

`John`

by generic Hangul stripping.

---

## 11. Script Ownership Guard

After approved boundary refinement, a canonical `PERSON_EN` candidate must not contain Hangul code points.

If Hangul remains inside the candidate after approved possessive or postposition refinement, the result must not be emitted as `PERSON_EN`.

A Hangul-only upstream candidate must never be relabeled to `PERSON_EN`.

This guard protects the L3/L4 ownership boundary and prevents arbitrary Hangul deletion.

---

## 12. Refinement Order

Canonical end-boundary refinement must follow this order:

1. remove one approved terminal Korean postposition using longest-match-first semantics, if present;
2. remove a terminal ASCII `'s` or Unicode `’s` possessive suffix, if present;
3. bind `original_value` again from the refined raw coordinates;
4. apply the script ownership guard;
5. emit only if the final candidate remains valid.

No generic Hangul trimming is authorized.

Internal name punctuation remains protected by the rules in this contract.

---

## 13. Ambiguous Single-Token Names

The implementation must not add a capitalization heuristic or other deterministic fallback for ambiguous single-token names.

Observed upstream behavior includes model-dependent differences such as:

- `Jordan` not emitted in one discovery case;
- `Taylor` emitted in one discovery case.

These observations do not authorize a new rule-based person detector.

Emission remains dependent on the approved MODEL producer.

---

## 14. Negative Boundaries

The implementation must not reinterpret ordinary organization, location, or generic identifier results as `PERSON_EN`.

Discovery negatives included:

- `Microsoft`
- `Seattle`
- a generic numeric order identifier

No additional deterministic fallback is authorized by this contract.

---

## 15. Failure Behavior

Failure to initialize or execute the required PERSON_EN model capability must fail closed.

The runtime must not silently:

- downgrade to a capitalization heuristic;
- use a different unapproved model;
- relabel unrelated entity types;
- emit fabricated confidence values.

---

## 16. Existing L3 Runtime Isolation

The currently frozen L3 runtime uses the existing Korean-side Analyzer boundary for already implemented entities.

PERSON_EN implementation must not require a global migration of the existing L3 Analyzer configuration unless a separate incompatibility is proven and adjudicated.

Existing frozen runtime behavior for entities such as EMAIL, PHONE, AGE, AGE_GROUP, DATE_OF_BIRTH, and LOCATION must remain unchanged.

---

## 17. Non-Goals

R6 PERSON_EN does not:

- implement `PERSON_KO`;
- redesign L4;
- change common detection schema;
- redefine confidence semantics;
- replace existing frozen recognizers;
- install a new NLP model;
- widen PERSON_EN into a generic capitalization detector.

---

## 18. DetectionTier Adjudication

`PERSON_EN` is classified as:

`MODEL`

Rationale:

The emission decision originates from spaCy NER through Presidio `SpacyRecognizer`.

The result is not proven by deterministic validation or a rule-anchored parser.

---

## 19. R6-S2B Decision

The following are approved for RED-test construction:

- upstream `PERSON`;
- canonical relabel to `PERSON_EN`;
- `tier = MODEL`;
- `confidence = null`;
- project-owned source `PersonEnRecognizer`;
- raw-coordinate preservation;
- terminal possessive refinement;
- approved Korean postposition refinement;
- no Hangul in final PERSON_EN canonical span;
- no deterministic single-token fallback;
- L4 `PERSON_KO` ownership preservation.

Implementation is not authorized until the corresponding RED contract tests are established.
