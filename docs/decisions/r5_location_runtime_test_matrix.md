# R5-S3 — LOCATION Runtime Test Matrix

Status: PROVISIONAL

Target Entity: `LOCATION`

Layer: `L3`

Authoritative Baseline: `c63caba9a0fe907af8ce13efb74c9871588204cb`

Parent Behavior Contract:
`docs/decisions/r5_location_runtime_behavior_contract.md`

Parent Contract SHA256:
`E48A672E47D0E6F116F6CE8C3985EF7EA87A259EB6D96006E5224B1F3E1A6450`

---

## 1. 목적

본 문서는 LOCATION runtime 구현 전에 검증해야 할 테스트 항목과
기대 결과를 사전 정의한다.

R5-S3에서는 테스트 코드를 작성하지 않는다.

R5-S3의 목적은 구현 결과에 맞추어 테스트를 사후 변경하는 것을 막고,
R5-S2 Behavior Contract를 검증 가능한 test obligation으로 변환하는 것이다.

Production LOCATION 구현은 R5-S4 Tests-first 이전에 시작하지 않는다.

---

## 2. 최상위 기준

LOCATION 테스트의 최상위 data contract는 다음이다.

    src/privacy_proxy/schemas.py

R5-S3 test expectation은 다음 우선순위를 따른다.

    1. src/privacy_proxy/schemas.py
    2. R5-S2 LOCATION Runtime Behavior Contract
    3. current canonical L3 runtime boundary
    4. FINAL L3/L4 ownership contract
    5. LOCATION v0.1.1 FINAL_FROZEN evidence

테스트를 통과시키기 위해 `schemas.py` 또는 R5-S2 계약을
임의 변경하지 않는다.

계약과 구현 사이에 충돌이 발생하면 구현을 우선 수정한다.

---

## 3. Test Philosophy

LOCATION 테스트는 다음 원칙을 따른다.

    behavior first
    tests before implementation
    raw-coordinate preservation
    exact producer provenance
    fail-closed dependency handling
    frozen evidence preservation
    no hidden schema widening
    no silent L3/L4 ownership expansion

Presidio numeric score는 canonical confidence 또는 tier의
독립적인 증거로 사용하지 않는다.

---

## 4. Test Layer

테스트는 크게 다음 세 수준으로 구분한다.

### UNIT

개별 producer, refinement, tier, provenance 동작을 검증한다.

외부 model 자체가 핵심 검증 대상이 아닌 경우 mock 또는
controlled dependency를 사용할 수 있다.

### INTEGRATION

실제 L3 service / registry / adapter boundary를 통과하여
canonical `DetectedPII` 결과를 검증한다.

### FROZEN REGRESSION

기존 LOCATION frozen evidence와 새 runtime의 동작이
계약 범위 내에서 유지되는지 검증한다.

실제 `ko_core_news_lg` 모델은 최소 한 번 이상의 integration /
frozen regression 경로에서 사용해야 한다.

Unit test mock만으로 model integration 성공을 선언하지 않는다.

---

# 5. Canonical Schema Tests

## S01 — Canonical Nine-Field Schema

Test Type: UNIT

검증:

    DetectedPII field order

Expected:

    segment_id
    start_idx
    end_idx
    entity_type
    confidence
    source
    tier
    original_value
    normalized

PASS 조건:

    정확히 9개 canonical field
    LOCATION 전용 extra field 없음

---

## S02 — Canonical LOCATION Mapping

Test Type: UNIT

Expected:

    entity_type = LOCATION
    confidence = None
    tier = MODEL

PASS 조건:

    LOCATION canonical object 생성 가능
    confidence None 허용
    DetectionTier.MODEL 허용

---

## S03 — Raw Coordinate Invariant

Test Type: UNIT + INTEGRATION

Invariant:

    raw_prompt[start_idx:end_idx] == original_value

PASS 조건:

    모든 LOCATION result에서 invariant 유지

FAIL 조건:

    transformed coordinate 사용
    normalized buffer coordinate 사용
    span / original_value mismatch

---

## S04 — normalized Mapping

Test Type: UNIT + INTEGRATION

Expected:

    normalized = original_value

PASS 조건:

    current LOCATION runtime에서 두 값 일치

현재 단계에서는 전국 행정구역 canonical lookup을 수행하지 않는다.

---

## S05 — Extra Metadata Rejection

Test Type: UNIT

Canonical `DetectedPII`에 다음 field를 직접 추가하면 안 된다.

    admin_type
    detail_level
    normalization_rule
    removed_suffix

Expected:

    schema validation rejection

PASS 조건:

    extra metadata가 canonical nine-field contract에 침투하지 않음

---

# 6. Registry / Producer Tests

## P01 — LOCATION Producer Registration

Test Type: UNIT

Pre-implementation:

    LOCATION producer absent

Post-implementation expected:

    LOCATION producer exactly 1

---

## P02 — Producer Count Transition

Test Type: UNIT

Current producer count:

    10

Expected after LOCATION implementation:

    11

PASS 조건:

    기존 producer 삭제 없음
    duplicate producer 없음
    LOCATION producer 정확히 1개

---

## P03 — Exact Producer Type

Test Type: UNIT

Expected:

    registry PRODUCER_TYPES["LOCATION"]
    = exact LocationRecognizer class

PASS 조건:

    subclass / unrelated producer로 우회하지 않음
    current registry exact-type verification 유지

---

## P04 — Producer Capability

Test Type: UNIT

Expected:

    supported_language = ko
    supported_entities = ["LOCATION"]

FAIL 조건:

    다중 entity producer
    non-ko producer
    LOCATION_INFORMAL 포함
    ADDRESS 포함

---

## P05 — Canonical Source Provenance

Test Type: UNIT + INTEGRATION

Expected:

    source = actual LOCATION producer.name

PASS 조건:

    resolve_producer()가 실제 등록 producer를 반환
    canonical source가 해당 producer.name과 일치

Historical producer name을 임의 하드코딩하지 않는다.

---

## P06 — Conflicting Producer Metadata

Test Type: UNIT

Input:

    result metadata recognizer name 또는 identifier가
    actual producer와 충돌

Expected:

    provenance failure

FAIL 조건:

    conflicting metadata를 무시하고 detection 성공 처리

---

# 7. DetectionTier Tests

## T01 — LOCATION Tier

Test Type: UNIT + INTEGRATION

Expected:

    DetectionTier.MODEL

PASS 조건:

    verified LocationRecognizer result만 MODEL로 mapping

---

## T02 — Unverified Producer Rejection

Test Type: UNIT

Input:

    LOCATION entity label
    but unverified producer identity

Expected:

    provenance / tier failure

FAIL 조건:

    entity_type 문자열만 보고 MODEL 반환

---

## T03 — Numeric Score Is Not Tier Evidence

Test Type: UNIT

Input:

    서로 다른 model / Presidio numeric score

Expected:

    score 변화 자체가 tier를 변경하지 않음

Canonical tier:

    MODEL

---

# 8. R01 Tests

## R01-A — Controlled Suffix Trim

Test Type: UNIT

Representative input:

    경기도에

Expected final LOCATION:

    경기도

Expected:

    refined end offset
    raw-coordinate invariant 유지
    original_value = 경기도
    normalized = 경기도
    tier = MODEL

---

## R01-B — Other Frozen Controlled Suffixes

Test Type: UNIT / FROZEN REGRESSION

검증 대상:

    에
    이고
    입니다

Expected:

    승인된 terminal suffix만 제거

---

## R01-C — Arbitrary Trimming Forbidden

Test Type: UNIT

Expected:

    controlled suffix 규칙 밖 substring을 임의로 제거하지 않음

---

# 9. R02 Tests

## R02-A — One Raw Candidate to Multiple Results

Test Type: UNIT

Representative raw candidate:

    경기도 수원시 영통구에

Expected canonical outputs:

    경기도
    수원시
    영통구

Expected count:

    3

---

## R02-B — Independent Raw Coordinates

Test Type: UNIT + INTEGRATION

각 emitted unit에 대해:

    raw_prompt[start_idx:end_idx] == original_value

PASS 조건:

    세 LOCATION 모두 자신의 raw coordinate 사용

---

## R02-C — Adapter Contract Preservation

Test Type: INTEGRATION

Expected architecture:

    LocationRecognizer
        -> RecognizerResult N개
        -> existing adapter
        -> DetectedPII N개

PASS 조건:

    common detection_adapter의
    1 RecognizerResult -> 1 DetectedPII 계약 유지

FAIL 조건:

    adapter가 LOCATION 전용 list decomposition 수행

---

## R02-D — No Parent Inference

Test Type: UNIT

Expected:

    model / raw candidate에 존재하지 않는 행정구역을
    추가 생성하지 않음

---

# 10. R03 Tests

## R03-A — Ambiguous Concatenated Compound

Test Type: UNIT + FROZEN REGRESSION

Representative inputs:

    경기도수원시영통구
    수원시영통구
    부산광역시해운대구

Expected:

    LOCATION emission = 0
    exception = none

---

## R03-B — Graceful Rejection Semantics

Test Type: INTEGRATION

Expected:

    R03 candidate rejection은 정상 control flow

FAIL 조건:

    L3RuntimeError
    dependency failure 처리
    oversized LOCATION false accept

---

# 11. R04 Tests

## R04-A — Unsupported Token

Test Type: UNIT + FROZEN REGRESSION

Representative inputs:

    영통구에서
    강남구였으며

Expected:

    LOCATION emission = 0
    exception = none

---

## R04-B — Graceful Rejection Semantics

Test Type: INTEGRATION

Expected:

    정상 candidate rejection

FAIL 조건:

    unhandled exception
    L3 runtime dependency failure로 승격

---

# 12. Model Boundary Tests

## M01 — LC Only

Test Type: UNIT + INTEGRATION

Expected:

    ko_core_news_lg의 승인된 LC candidate만
    L3 LOCATION 후보로 사용

FAIL 조건:

    다른 model label을 LOCATION으로 임의 mapping

---

## M02 — Model Miss Preservation

Test Type: UNIT + FROZEN REGRESSION

Expected:

    model이 탐지하지 않은 LOCATION은
    refinement가 새로 생성하지 않음

Historical oracle:

    B08 EXPECTED_LIMITATION

---

## M03 — Model Score Isolation

Test Type: UNIT

Expected:

    model numeric score는 canonical confidence에 복사되지 않음

Canonical:

    confidence = None

---

# 13. Dependency Failure Tests

## D01 — Model Missing

Test Type: UNIT + INTEGRATION

Condition:

    ko_core_news_lg dependency unavailable

Expected:

    explicit dependency/runtime failure

FAIL 조건:

    return []
    successful zero-detection으로 위장

---

## D02 — Model Load Failure

Test Type: UNIT

Condition:

    model load raises exception

Expected:

    fail closed

Public error에서는 sensitive dependency exception text를
그대로 노출하지 않는다.

---

## D03 — Model Inference Failure

Test Type: UNIT

Condition:

    model invocation raises unexpected exception

Expected:

    runtime failure

FAIL 조건:

    empty LOCATION list로 silently degrade

---

## D04 — Graceful Rejection vs Dependency Failure

Test Type: UNIT + INTEGRATION

Expected distinction:

    R03 / R04
        = normal zero-emission

    missing/load/inference failure
        = runtime failure

두 상태가 동일한 결과로 collapse되면 FAIL이다.

---

# 14. Frozen Regression Tests

## F01 — L01-L08 Raw Binding Regression

Test Type: FROZEN REGRESSION

Historical expectation:

    Raw LC total            = 9
    LOCATION total          = 9
    start match             = 9 / 9
    end match               = 9 / 9
    surface match           = 9 / 9
    full span match         = 9 / 9

---

## F02 — Controlled Normalizer Regression

Test Type: FROZEN REGRESSION

Historical expectation:

    Raw LOCATION spans = 9
    Normalized units   = 15
    R01 units          = 6
    R02 units          = 9
    Exact recovery     = 15 / 15

---

## F03 — B01-B08 v0.1.1 Regression

Test Type: FROZEN REGRESSION

Expected:

    B01 = GRACEFUL_REJECTION
    B02 = GRACEFUL_REJECTION
    B03 = GRACEFUL_REJECTION
    B04 = GRACEFUL_REJECTION
    B05 = GRACEFUL_REJECTION
    B06 = STRUCTURAL_SUCCESS
    B07 = STRUCTURAL_SUCCESS
    B08 = EXPECTED_LIMITATION

Aggregate expectation:

    STRUCTURAL_SUCCESS          = 2
    EXPECTED_LIMITATION         = 1
    UNDERSEGMENTED_FALSE_ACCEPT = 0
    GRACEFUL_REJECTION          = 5
    UNHANDLED_EXCEPTION         = 0

---

# 15. Integration Tests

## I01 — Requested LOCATION Isolation

Test Type: INTEGRATION

When:

    entities = ["LOCATION"]

Expected:

    returned result entity_type는 LOCATION만 존재

---

## I02 — LOCATION Not Requested

Test Type: INTEGRATION

LOCATION text가 존재하더라도 request entity set에 LOCATION이
포함되지 않은 경우 LOCATION result가 반환되면 안 된다.

기존 service requested-entity isolation을 유지한다.

---

## I03 — Mixed Existing L3 Entities

Test Type: INTEGRATION

Representative prompt에는 LOCATION과 기존 L3 entity를 함께 둔다.

예:

    LOCATION
    EMAIL_ADDRESS
    PHONE_NUMBER

Expected:

    기존 entity 동작 유지
    LOCATION 추가로 기존 detection 제거 없음
    canonical schema 동일

---

## I04 — segment_id Propagation

Test Type: INTEGRATION

Expected:

    caller가 제공한 segment_id가
    LOCATION DetectedPII에 그대로 전달

---

## I05 — Existing Adapter Boundary

Test Type: INTEGRATION

Expected:

    LOCATION result도 기존 detection_adapter를 사용하여
    canonical DetectedPII로 변환

LOCATION 전용 별도 canonical schema 경로를 만들지 않는다.

---

# 16. Ownership / Scope Tests

## B01 — LOCATION_INFORMAL Non-Expansion

Test Type: UNIT + INTEGRATION

Representative informal expressions:

    강남 쪽
    역삼 근처
    저희 동네

Expected:

    L3 LOCATION이 이 표현을 새 ownership으로 획득하지 않음

L4 LOCATION_INFORMAL 책임 유지.

---

## B02 — ADDRESS Non-Expansion

Test Type: UNIT + INTEGRATION

LOCATION 구현은 다음 entity를 새로 emit하지 않는다.

    ADDRESS
    ADDRESS_ROAD
    ADDRESS_LOT
    ADDRESS_DETAIL

---

## B03 — Historical Metadata Internal Only

Test Type: UNIT

다음 정보는 canonical DetectedPII field가 아니다.

    admin_type
    detail_level
    normalization_rule
    removed_suffix

Expected:

    내부 판단 또는 test evidence로만 사용

---

# 17. Existing Runtime Regression Tests

## G01 — Existing Ten Producers Preserved

Test Type: UNIT

LOCATION 추가 전 producer:

    10

LOCATION 추가 후:

    11

Expected:

    기존 10 producer type / capability가 변경되지 않음

---

## G02 — Existing Ten Entity Behavior Preserved

Test Type: REGRESSION

기존 지원 entity의 test suite를 그대로 통과해야 한다.

특히:

    KR_RRN
    KR_FRN
    KR_PASSPORT
    KR_DRIVER_LICENSE
    KR_BRN
    PHONE_NUMBER
    EMAIL_ADDRESS
    AGE
    AGE_GROUP
    DATE_OF_BIRTH

LOCATION 구현 때문에 기존 runtime behavior를 변경하지 않는다.

---

## G03 — Global Analyzer Boundary Preserved

Test Type: UNIT + INTEGRATION

Expected:

    existing global AnalyzerEngine configuration 유지
    LOCATION 구현만을 위해 전역 spaCy migration 없음

기존 NoOp NLP boundary를 LOCATION producer 외부에서
임의 변경하지 않는다.

---

# 18. Test Data Rules

테스트 데이터에는 실제 개인정보를 사용하지 않는다.

LOCATION fixture는 synthetic / controlled geographic text만 사용한다.

Historical frozen fixture를 재사용하는 경우:

    frozen original은 수정하지 않는다.

필요한 경우 별도 runtime test fixture를 생성한다.

새 fixture가 historical artifact 자체를 대체하거나
수정해서는 안 된다.

---

# 19. Model Test Strategy

Model-related tests는 다음처럼 분리한다.

Unit:

    dependency mock 가능
    controlled LC result 사용 가능
    error injection 가능

Integration:

    실제 registry / service / adapter 경계 사용

Real Model Regression:

    실제 ko_core_news_lg를 사용
    frozen regression 최소 1회 수행

Mock-only PASS로 LOCATION model runtime 완료를 선언하지 않는다.

---

# 20. R5-S4 RED Test Requirement

R5-S4 Tests-first 단계에서는 구현보다 먼저
LOCATION behavior test를 작성한다.

새 LOCATION capability 관련 test는 최초 실행에서
현재 implementation gap 때문에 RED가 예상된다.

특히 최소 다음은 implementation 전에 실패해야 한다.

    LOCATION producer registration
    producer count 11
    LOCATION exact producer identity
    tier MODEL mapping
    R01 runtime behavior
    R02 runtime behavior
    R03 runtime behavior
    R04 runtime behavior
    dependency failure behavior

현재 이미 성립하는 shared schema test까지
억지로 RED로 만들 필요는 없다.

RED의 목적은 새 LOCATION capability가 아직 구현되지 않았음을
증명하는 것이다.

---

# 21. Implementation Authorization Boundary

R5-S3 자체는 다음 변경을 승인하지 않는다.

    src/privacy_proxy/l3/location_recognizer.py 생성
    registry.py 수정
    tier_mapping.py 수정
    analyzer_factory.py 수정
    detection_adapter.py 수정
    service.py 수정
    pyproject.toml 수정
    tests/ 수정

이 변경은 R5-S3가 검증 완료된 후
R5-S4 Tests-first 단계에서 순차적으로 진행한다.

---

# 22. R5-S3 Exit Criteria

R5-S3 완료 조건:

    parent R5-S2 contract hash exact match
    canonical schema tests defined
    registry tests defined
    provenance tests defined
    tier tests defined
    R01 tests defined
    R02 tests defined
    R03 tests defined
    R04 tests defined
    model-miss test defined
    dependency failure tests defined
    frozen regression tests defined
    integration tests defined
    L3/L4 boundary tests defined
    ADDRESS non-expansion test defined
    existing-runtime regression tests defined
    model real-integration requirement defined
    production source unchanged
    tests directory unchanged
    LOCATION implementation not started

---

# 23. Next Phase

R5-S3 검증 완료 후 다음 단계:

    R5-S4 — LOCATION Tests-First

R5-S4에서는 본 matrix를 기준으로 실제 test code를 먼저 작성한다.

R5-S4 test implementation 이후 최초 RED evidence를 확인하기 전에는
production LocationRecognizer 구현을 시작하지 않는다.
