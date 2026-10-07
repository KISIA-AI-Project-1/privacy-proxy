# P4 AGE_GROUP Runtime Final Freeze

Status: FINAL_FROZEN
Entity: AGE_GROUP
Layer: L3
Freeze ID: P4
Freeze Time: 2026-10-06T10:44:40+09:00

---

## 1. Authorization

- H3-R1 STATUS: PASS_WITH_FINDINGS
- Blocking findings: NONE
- Unauthorized AGE_GROUP semantic/architecture drift: NO
- FREEZE ENTRY: YES

The previous blocking findings F1, F2, and F3 are CLOSED.

---

## 2. Baseline

- Branch: feature/detection
- Baseline HEAD: f3c0531f2d27b963611568483c04a6a16b9e86b3
- origin/develop: f3c0531f2d27b963611568483c04a6a16b9e86b3

---

## 3. Frozen AGE_GROUP Semantic Contract

Supported decade values:

- 10대
- 20대
- 30대
- 40대
- 50대
- 60대
- 70대
- 80대
- 90대

Supported refinements:

- 초반
- 중반
- 후반

Refined detections bind the complete approved raw span.
Rejected or deferred larger surfaces must not fall back to an inner valid decade.
Question, conditional, statistical, recommendation-target, malformed numeric, range and collision contexts remain rejected according to the approved H1-R1/H2 contract.
Independent valid clauses remain detectable when a separate clause is rejected.

---

## 4. Canonical Detection Contract

- entity_type = AGE_GROUP
- confidence = null
- source = AgeGroupStatementRecognizer
- tier = rule_anchored
- original_value = raw_prompt[start_idx:end_idx]
- normalized = original_value
- offsets = zero-based, half-open

No AGE_GROUP-specific DTO or adapter fork is approved.

---

## 5. Entity-Owned Frozen Files

- src/privacy_proxy/l3/age_group_recognizer.py | SHA256=8FFC39E4FC672B7FB7DF1DA829FA6735DB7D8CFE4DDFFE5048355C97C7242F8C
- tests/unit/test_age_group.py | SHA256=270D3D08E8F6C7B228951F6B43E92D88414D4775119796F9CB65F806FC0A8E6B
- tests/integration/test_age_group_runtime.py | SHA256=F234712B386B9A75F77F3A496BC9B373D1BE0FDFFF5784ED94EFC35C794752B2

These three files are the AGE_GROUP entity-owned semantic freeze scope.
Any AGE_GROUP semantic modification to them requires a new review/evidence cycle.

---

## 6. Cross-Layer Compatibility Evidence

- tests/vault/test_nullable_confidence.py | SHA256=83880CCD9128BD7F64ABBACA69F3AFA30D0FD9531211210F34BD5B46B2D7DD79

This file records the approved L6 nullable-confidence compatibility evidence.
Canonical L3 AGE_GROUP confidence remains null.

---

## 7. Shared Dependency Snapshot

- src/privacy_proxy/l3/registry.py | SHA256=3013792BC32845CA1A900ED52C2B69990BFEB35E98374B74B29DB4990C41D348
- src/privacy_proxy/l3/tier_mapping.py | SHA256=DD3F37869552496680F9397FED78D5D13E3BBD6D83303DB0B77FAB3232E9335D
- src/privacy_proxy/vault/tokenizer.py | SHA256=363878CBAFC250730D29A6258993ECE891EB33193FA14F68FD6A9515774926F6
- tests/integration/test_age_runtime.py | SHA256=F435B6F508FCB38ED7E59020D35663E2C040A5BC97B40AF75C28DF86F602C59E
- tests/unit/test_l3.py | SHA256=015942789118D310433E2038A9ECF3661E5529122407E03F01459756F2F2FBE8
- tests/unit/test_phone.py | SHA256=0BBC9BAA1D14C43DBD514E79ADFBC443FE0C08E89A89A4143709ED9213D27B6E
- tests/unit/test_email.py | SHA256=5384BA9DE1E7D8AB1AEE86882C88B54EA203F750BAB1D68BF3FB25F369BED9CB

These hashes are reproducibility snapshots only.
They do not grant blanket semantic authorization to unrelated behavior contained in a shared file.
A shared dependency change that can affect AGE_GROUP requires AGE_GROUP regression verification.

---

## 8. EMAIL_ADDRESS Separation

This AGE_GROUP freeze does not approve, freeze, or adjudicate separate EMAIL_ADDRESS semantic work.

EMAIL-specific work, including changes involving:

- src/privacy_proxy/l3/email_validation.py
- tests/unit/test_email.py

belongs to a separate review and evidence cycle.

---

## 9. Existing AGE Freeze Preservation

The existing AGE final freeze remains preserved.

Verified anchors:

- src/privacy_proxy/schemas.py
- src/privacy_proxy/l3/age_recognizer.py
- tests/unit/test_age.py
- docs/decisions/d7-e-age-runtime-final-freeze.md

AGE and AGE_GROUP remain independent producers and independent raw-span detections.

---

## 10. Verification Chain

- H1-R1: PASS
- H2: PASS
- H2-R1: PASS
- M1-R1: PASS
- P2: PASS
- P3: PASS
- H3: FAIL
- M1-R2: PASS
- P2-R2: PASS after supplemental TAB evidence confirmation
- P3-R2: PASS
- H3-R1: PASS_WITH_FINDINGS

H3-R1 independently closed F1, F2 and F3.

---

## 11. Non-Blocking Findings

- Starlette/httpx deprecation warning
- accepted tokenizer EOL-only normalization
- existing plain/refined downstream equivalence
- existing refined GENERALIZE passthrough limitation

None of these findings blocks AGE_GROUP final freeze.

---

## 12. Freeze Rules

- Do not redesign AGE_GROUP semantics without a newly proven incompatibility.
- Do not silently change entity-owned frozen AGE_GROUP files.
- Any AGE_GROUP semantic change requires a new review/evidence cycle.
- Preserve canonical DetectedPII.
- Preserve confidence=None for L3 AGE_GROUP.
- Preserve DetectionTier.RULE_ANCHORED.
- Preserve exact raw-span binding.
- Preserve no-substring-fallback behavior.
- Preserve fail-closed behavior.
- Preserve the existing AGE freeze.
- Keep EMAIL_ADDRESS remediation outside AGE_GROUP authorization.

---

## 13. Final State

P4_AGE_GROUP_FREEZE = FINAL_FROZEN

Commit / push / PR / merge have NOT been performed by this freeze step.
