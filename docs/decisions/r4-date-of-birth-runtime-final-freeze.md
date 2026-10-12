# R4 DATE_OF_BIRTH Runtime Final Freeze

Status: FINAL_FROZEN
Entity: DATE_OF_BIRTH
Layer: L3
Freeze ID: R4-1F-F3
Freeze Time: 2026-10-08T18:16:35+09:00

---

## 1. Freeze Authorization

R4-1F-F2 completed with:

- FREEZE READINESS = PASS
- BLOCKER = NONE
- FINAL_FREEZE_ENTRY = AUTHORIZED

No functional, regression, static-quality, schema, contract, or
workspace-integrity blocker remained at freeze entry.

---

## 2. Authoritative Baseline

- Branch: feature/detection
- Baseline HEAD: 6d9165e97182ec0b56cb9d72e518c8bc28ece47e
- Baseline Tree: 64723827cd2259b57601d4589ffdd41e6247e83c

The DATE_OF_BIRTH implementation is intentionally frozen from the
verified working-tree state represented by the file-level SHA256
anchors below.

---

## 3. Frozen DATE_OF_BIRTH Runtime Contract

DATE_OF_BIRTH is SUPPORTED by L3.

Producer:

- DateOfBirthRecognizer

Canonical output requirements:

- entity_type = DATE_OF_BIRTH
- confidence = null
- source = actual DateOfBirthRecognizer producer
- tier = DetectionTier.RULE_ANCHORED
- original_value = raw_prompt[start_idx:end_idx]
- normalized = original_value
- offsets = zero-based, half-open
- current single-segment boundary preserved
- existing fail-closed behavior preserved

No DATE_OF_BIRTH-specific common DTO fork is approved.

---

## 4. Frozen Semantic Boundary

Supported surface forms:

- ISO exact YYYY-MM-DD
- compact YYYYMMDD
- Korean-native YYYY년 M월 D일

Birth semantics require approved birth-context evidence.

Approved prefix anchors:

- 생년월일
- 생일

Approved Korean-native suffix evidence:

- 생

A valid calendar date alone is not sufficient evidence of
DATE_OF_BIRTH.

The frozen recognizer preserves:

- real Gregorian calendar validation
- invalid-date rejection
- future-date rejection
- UTC-date evaluation seam
- clause-local anchor evidence
- bounded anchor distance
- explicit boundary protection
- exact raw span binding
- no duplicate detection identity
- timeout observability
- unexpected runtime failure observability

---

## 5. Integration Freeze

Registry integration:

- DATE_OF_BIRTH -> DateOfBirthRecognizer

Capability status:

- DATE_OF_BIRTH = SUPPORTED

Detection tier:

- DATE_OF_BIRTH = RULE_ANCHORED

The existing generic service, analyzer factory, detection adapter,
and canonical schema are reused without a DATE_OF_BIRTH-specific fork.

---

## 6. Final Freeze Artifact SHA256 Manifest

- docs/decisions/r4-1c-date-of-birth-behavior-contract.md
  - SHA256: 89301C5EEDAD67E893A908CCCB6A56D7A9B393A5A28ABA401B74AFE1FBFBD203

- docs/decisions/r4-1d-date-of-birth-unit-test-matrix.md
  - SHA256: 589144220571AFF7A97B9E0E842650EBD5A95DE32D6DFF4785D67CBE80913A16

- src/privacy_proxy/l3/date_of_birth_recognizer.py
  - SHA256: 9B0C56399F5D8C0DF5904F2DAB93DF527235F9B896181BE44EED0A01817C043B

- src/privacy_proxy/l3/registry.py
  - SHA256: DFDB5A3E4CAEEE40D7C3238A71E97FEB2E4ED3B290B450AD5BF3F4CA2C7824B3

- src/privacy_proxy/l3/tier_mapping.py
  - SHA256: FC6175D718FF15A93EAAD5AC158BCC118D7E92B322A45B1687CDDDE0B140991F

- tests/unit/test_date_of_birth.py
  - SHA256: 3B50709BF5FA18B8092F25FDA5FB783DFA29C125B28BA4850056BBB808F21EF1

- tests/integration/test_date_of_birth_runtime.py
  - SHA256: E8BE1125B36D63316646DD713971FC5EF7D567686B04AD881FE5BAEA4C5813EB

- tests/integration/test_age_group_runtime.py
  - SHA256: 457E49844AD4C66AD4FBF718BFA11408AF26A0A3EA8CAC0D4A7C39084EACF19C

- tests/integration/test_age_runtime.py
  - SHA256: 810E4AEB081889F5F72ACA55A29A046A96093E18C1C41681BE05F784BF126C75

- tests/unit/test_email.py
  - SHA256: 3C1E17E0E4713E4A9333952D6E0256CB6AA0E729652E4A735B381C675AA0BDC4

- tests/unit/test_l3.py
  - SHA256: ED461F8111AD9111765D0C6E1670301E6EFECB9A89F553683BE1CE6FA8615B0B

- tests/unit/test_phone.py
  - SHA256: 3F89525B8717C86F67A29A3F462AFF48E6E703AD0047BCFEDFDCCD150D219871

These twelve files form the DATE_OF_BIRTH implementation,
integration, compatibility, and evidence freeze scope.

---

## 7. Protected Common Architecture

The following files remained unchanged at freeze entry:

- src/privacy_proxy/schemas.py
- src/privacy_proxy/contracts/detection.py
- src/privacy_proxy/l3/service.py
- src/privacy_proxy/l3/detection_adapter.py
- src/privacy_proxy/l3/analyzer_factory.py
- src/privacy_proxy/l3/age_recognizer.py
- src/privacy_proxy/l3/age_group_recognizer.py

No common schema modification was required.

No detection-contract modification was required.

No service or adapter fork was required.

---

## 8. Final Verification Evidence

Final verification before freeze:

- DOB targeted regression: PASS
- full repository regression: PASS
- Ruff lint: PASS
- Ruff format check: PASS
- mypy: PASS
- git diff --check: PASS
- mixed line endings: NONE
- protected common architecture: UNCHANGED
- tracked working-tree scope: EXPECTED
- staging area: EMPTY

Candidate Python quality scope:

- 113 Python files
- Ruff lint PASS
- Ruff format PASS

mypy result:

- no issues in 44 source files

---

## 9. Line Ending Disposition

Individual files use either LF or CRLF.

No frozen file contained mixed line endings.

The recurring Git warning that selected LF working-tree files may be
converted to CRLF when Git next touches them is therefore classified
as NON_BLOCKING at this freeze point.

No automatic EOL normalization is part of this freeze.

---

## 10. Known Non-Blocking Warning

Full pytest emits a StarletteDeprecationWarning related to
FastAPI TestClient / httpx compatibility.

Disposition:

NON_BLOCKING_DEPENDENCY_WARNING

Reason:

- full repository regression exits successfully
- warning is not DATE_OF_BIRTH-specific
- no dependency migration is authorized as part of this runtime freeze

---

## 11. Unrelated Local Workspace Artifacts

The following pre-existing local artifacts are explicitly excluded
from the DATE_OF_BIRTH freeze scope:

- age_stash_full.patch
- evidence/
- pr12_diff.txt
- schema_review_develop.txt
- root schemas.py

These artifacts must not be staged, committed, deleted, or rewritten
as part of DATE_OF_BIRTH finalization.

---

## 12. Final Freeze Decision

DATE_OF_BIRTH runtime status:

FINAL_FROZEN

The following are closed:

- behavior contract
- unit-test matrix
- recognizer implementation
- registry integration
- DetectionTier integration
- compatibility migration
- targeted regression
- full repository regression
- static quality validation
- freeze readiness review

Any future change to DATE_OF_BIRTH semantics, producer behavior,
tier assignment, canonical mapping, or frozen files requires a new
explicit change decision and new verification evidence.

---

## 13. Final Status

R4-1F-F3 = PASS
R4-1F = PASS / CLOSED
DATE_OF_BIRTH = FINAL_FROZEN

---

## 14. Pre-Commit Whitespace Remediation

During R4-1G-B staged-diff validation, git diff --cached --check
identified Markdown trailing whitespace in the behavior-contract metadata
header. The four Markdown hard breaks were converted to explicit <br>
markers so rendered line breaks are preserved without trailing whitespace.

Scope:

- docs/decisions/r4-1c-date-of-birth-behavior-contract.md
- docs/decisions/r4-date-of-birth-runtime-final-freeze.md (manifest re-anchor only)

No runtime source, test semantics, schema, contract semantics, registry
mapping, DetectionTier assignment, or frozen behavior changed.

The behavior-contract SHA256 in this manifest was refreshed after this
format-only remediation.

---

## 15. Latest Develop Baseline Revalidation / Freeze Re-anchor

Re-anchor ID: R4-1G-D0-RB3-B
Revalidation Time: 2026-10-09T18:12:43+09:00

### 15.1 Historical Freeze Preservation

The original R4-1F-F3 final-freeze baseline remains part of the
historical evidence and is not rewritten:

- Original Baseline HEAD: 6d9165e97182ec0b56cb9d72e518c8bc28ece47e
- Original Baseline Tree: 64723827cd2259b57601d4589ffdd41e6247e83c

This addendum does not replace or reinterpret the original freeze event.

### 15.2 Revalidated Develop Baseline

Before local commit creation, origin/develop advanced beyond the original
freeze baseline. The feature/detection baseline was therefore advanced
by fast-forward only after exact-path overlap review.

- Revalidated Baseline HEAD: 4d1b5334bf8afd9db60838ff9f18d7c7d47c39ed
- Revalidated Baseline Tree: 27efe691ed5143684785869a1d894ecd9c9737f5
- origin/develop: 4d1b5334bf8afd9db60838ff9f18d7c7d47c39ed
- Baseline advance mode: FF_ONLY

### 15.3 Upstream Compatibility Evidence

Latest-develop compatibility review established:

- no upstream modification to src/privacy_proxy/l3/
- no upstream modification to src/privacy_proxy/contracts/detection.py
- canonical DetectedPII remains exactly nine fields
- DATE_OF_BIRTH remains registered through PRODUCER_TYPES
- DATE_OF_BIRTH tier remains RULE_ANCHORED through tier_for()
- required runtime imports remain available
- pytest remains available in the project environment

The upstream schemas.py change added ProxyContext.upstream_request_body
and did not alter the canonical DetectedPII field contract.

### 15.4 Revalidation Evidence

- R4-1G-D0-RB2-A-R2 = PASS
- LATEST_DEVELOP_COMPATIBILITY = CONFIRMED
- R4-1G-D0-RB2-B = PASS
- DOB TARGETED REGRESSION = GREEN
- R4-1G-D0-RB2-C = PASS
- L3 REGRESSION = GREEN
- FULL REGRESSION = GREEN
- STATIC QUALITY = GREEN
- Ruff lint = PASS
- Ruff format check = PASS
- mypy = PASS
- git diff --check = PASS

### 15.5 Frozen Artifact Preservation

The twelve non-self artifacts listed in the existing freeze manifest
remain byte-identical to their previously recorded SHA256 values.

No DATE_OF_BIRTH behavior, recognizer semantics, test semantics, registry
mapping, DetectionTier assignment, canonical output mapping, or L3
runtime contract was changed by the baseline advance.

### 15.6 Re-anchor Decision

DATE_OF_BIRTH remains FINAL_FROZEN.

The original freeze baseline remains historical evidence. This append-only
revalidation addendum establishes 4d1b5334bf8afd9db60838ff9f18d7c7d47c39ed as the validated
latest-develop baseline for pre-commit handoff.

Only this final-freeze document receives a new external SHA256 anchor as
a result of this re-anchor.

---

## 16. Pre-Commit Hook EOF Compliance Re-anchor

Re-anchor ID: R4-1G-D-R3
Re-anchor Time: 2026-10-09T18:24:27+09:00

### 16.1 Trigger

The first authorized local commit attempt was rejected by the repository
pre-commit end-of-file-fixer hook.

All preceding pre-commit checks passed, including Ruff lint, Ruff format,
hardcoded-secret detection, mypy, private-key detection, large-file
detection, merge-conflict detection, and trailing-whitespace validation.

The commit was not created.

### 16.2 Exact Hook Mutation

The hook modified exactly two frozen documentation artifacts:

- docs/decisions/r4-1c-date-of-birth-behavior-contract.md
- docs/decisions/r4-1d-date-of-birth-unit-test-matrix.md

For each file, byte-level verification established that the hook added
exactly one terminal LF byte (0x0A). Removing that one byte in memory
reproduced the previously frozen SHA256 exactly.

No text, semantics, test expectation, recognizer behavior, registry
mapping, DetectionTier assignment, canonical output contract, or runtime
implementation changed.

### 16.3 Hook-Compliant Authoritative SHA256 Overrides

The following values supersede the earlier SHA256 values for these two
artifacts for all subsequent staging and commit verification:

- docs/decisions/r4-1c-date-of-birth-behavior-contract.md
  - SHA256: D303924FB2B37E9CD25D0DDA21FFFDD01D606D35A263C53CC26B7C4CF8FB259A
- docs/decisions/r4-1d-date-of-birth-unit-test-matrix.md
  - SHA256: E4A4B8151476ED3B0F3EF8E8FCBCD1C822D7D3DDB3FC0C7F4A769A77B982942D

All other non-self DATE_OF_BIRTH freeze artifacts remain byte-identical
to their previously recorded authoritative SHA256 values.

### 16.4 Decision

Repository hook compliance is accepted as a format-only correction.

DATE_OF_BIRTH remains FINAL_FROZEN.

The prior hash records remain preserved as historical evidence of the
pre-hook freeze state. The two SHA256 values above are the authoritative
hook-compliant values for the next exact-restaging and commit gate.

This final-freeze document receives a new external SHA256 anchor after
this append-only re-anchor.
