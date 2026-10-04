# D7-E AGE Runtime Final Freeze

Status: FINAL_FROZEN
Entity: AGE
Layer: L3
Freeze ID: D7-E
Freeze Time: 2026-10-03T22:06:17+09:00

## 1. Freeze Anchor

Branch: feature/detection
Baseline HEAD: 37442156513c2fc7c37faa9b6e4e2cb034835f3b
Baseline Tree: 38316123c3e953cd6fbc810a4ac22dcc4e9a9bf3

The working implementation is intentionally uncommitted at this
freeze stage. File-level SHA256 values below are the immutable
working-tree freeze anchors.

## 2. Review Authorization

D7-D5 independent final re-review: PASS

AGE implementation review: PASS

D7-E freeze eligibility after blocker disposition: YES

No AGE semantic blocker remains.

## 3. Frozen AGE Runtime Contract

AGE is SUPPORTED.

Canonical output model:

DetectedPII

Frozen AGE output requirements:

- entity_type = AGE
- confidence = None
- source = actual AgeStatementRecognizer producer
- tier = DetectionTier.RULE_ANCHORED
- normalized = original_value
- raw_prompt[start_idx:end_idx] = original_value
- exact zero-based half-open span
- current single-segment boundary preserved
- existing fail-closed behavior preserved

No common schema change is part of this freeze.

src/privacy_proxy/schemas.py remained byte-identical to HEAD.

## 4. R4 Semantic Boundary

The D7-C-R4 semantic behavior is frozen.

Included protections:

- approved personal-age statements remain detectable
- approximate age expressions are rejected where defined by R4
- policy / recommendation age expressions are rejected
- relative / comparative age expressions are rejected
- lexical-collision protections are preserved
- predicate-continuation handling is preserved
- clause-local / bounded validation is preserved
- recognizer timeout behavior is preserved

## 5. Frozen AGE Files

- src/privacy_proxy/l3/age_recognizer.py | SHA256=7DC36A3335D235AC972F5170F3FA2A8C59982D78B93AF30506A1A2C7F407D39D
- src/privacy_proxy/l3/registry.py | SHA256=4532E1BDD909B8200A675A5E701E586412F0D1444E8D825B613CC15F07C929A3
- src/privacy_proxy/l3/tier_mapping.py | SHA256=32287E942FDA5EF0A52C8B9918C8D21C61F91A97148BE4001D7007CD16AFFB4E
- tests/unit/test_age.py | SHA256=B6F2BCB25D7381D5B6FF6ECE055AEF3B372EC15149F8B8D70843BF6CE8C394C8
- tests/integration/test_age_runtime.py | SHA256=E209F9A30CB14540A54A4F8DA4F6C36EDB363D19D17B0231671D0A5CB97125BB
- tests/unit/test_l3.py | SHA256=D9E2CF4875C105F3EFF8C790F4614A2BF116EB54CDE6BE921A6D051A614ECB14
- tests/unit/test_email.py | SHA256=B84BDFCCE13B155510A514D05BAE4EEF85121F0D9C9CB8DE569ECA448A296C91
- tests/unit/test_phone.py | SHA256=BF56DD4E45861BD4CD83F1AC4BF56024ECADC3FEBF092B6F5EFF71B359F58DC0

These eight files are the AGE semantic implementation/test freeze scope.

## 6. Final Verification Evidence

Final pre-freeze verification after all required remediation:

- full pytest: PASS
- result: 606 passed
- subtests: 74 passed
- coverage: 84 percent
- mypy: PASS — 61 source files
- candidate Ruff check: PASS — 97 Python files
- candidate Ruff format check: PASS — 97 Python files
- git diff --check: PASS
- canonical schema unchanged: YES

## 7. Local Workspace Ruff Disposition

Literal workspace commands:

- ruff check . = FAIL
- ruff format --check . = FAIL

Cause:

root-level schemas.py

Disposition:

NON_BLOCKING_LOCAL_UNTRACKED_ARTIFACT

Evidence:

- file is not tracked by Git
- file predates the AGE port
- SHA256 remained unchanged:
  D13AEB5647F948B6AD9E5FFDC04743E55C4F5D196C53B3CA7BD93A0EBF73D19D
- canonical src/privacy_proxy/schemas.py is unchanged
- tracked repository Python plus all three new AGE Python files pass
  Ruff and Ruff format checks

The local root schemas.py artifact is explicitly excluded from the
repository candidate and MUST NOT be staged or committed.

## 8. Repository-Gate Remediation Outside AGE Semantic Scope

The following files were changed after D7-D5 solely to resolve
pre-existing repository verification blockers:

- src/privacy_proxy/debug_detect.py | SHA256=86586E5D4C0672BC6FC3A25925480E1A587400073228F435D39CA827FCFEB6BD
- src/privacy_proxy/l3/__init__.py | SHA256=2388A19FA8C5AAAB1820F6E2817DFE8A201409B6EC860E3B7C942690A7B56E6B
- src/privacy_proxy/pipeline.py | SHA256=4CD634F8F0DD806C1F2FB8B5D525A90BC3A0C0FB2FBAB6821233A2BE17706D64
- tests/test_pipeline.py | SHA256=88E480ED3DEFCEE41059AA1A83C67F78E6A2CAEC2BC69F34484C51B1AC5B4D7C

Classification:

- src/privacy_proxy/debug_detect.py
  pre-existing Ruff formatting remediation

- src/privacy_proxy/l3/__init__.py
  canonical import-path remediation for mypy duplicate-module failure

- src/privacy_proxy/pipeline.py
  type-annotation-only remediation for strict mypy

- tests/test_pipeline.py
  stale test-seam migration from obsolete mock_l4_detection_ecommerce
  patching to the current L4 recognizer seam

These four files are NOT part of the AGE semantic implementation
freeze scope and must be identified separately in commit/PR history.

## 9. Remaining L3 Capability Boundary

Supported by this freeze:

AGE

Not implemented by this freeze:

- AGE_GROUP
- DATE_OF_BIRTH
- PERSON_EN
- LOCATION
- ADDRESS

This freeze does not authorize implementation of another entity.

## 10. Freeze Rules

From this point forward:

- do not redesign AGE R4 semantics without a new incompatibility
- do not change the eight frozen AGE files silently
- any AGE semantic change requires a new review/evidence cycle
- preserve the canonical DetectedPII contract
- preserve confidence=None for L3 AGE
- preserve DetectionTier.RULE_ANCHORED
- preserve exact raw-span binding
- preserve current single-segment boundary
- preserve fail-closed behavior

## 11. Final State

D7_E_AGE_FREEZE = FINAL_FROZEN

Commit / push / PR / merge have NOT been performed by this freeze step.
