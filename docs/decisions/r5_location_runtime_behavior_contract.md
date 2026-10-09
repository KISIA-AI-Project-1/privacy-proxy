# R5-S2 — LOCATION Runtime Behavior Contract

Status: PROVISIONAL

Target Entity: `LOCATION`

Layer: `L3`

Authoritative Baseline: `c63caba9a0fe907af8ce13efb74c9871588204cb`

Historical Reference: LOCATION Normalizer v0.1.1 `FINAL_FROZEN`

---

## 1. 목적

본 문서는 과거 실험에서 검증 및 동결된 LOCATION 탐지·정제 동작을
현재 `privacy-proxy-team` L3 runtime에 이식하기 위한 동작 계약을 정의한다.

R5-S2는 구현 단계가 아니다.

이 단계에서는 다음을 고정한다.

- LOCATION의 의미적 범위
- LOCATION producer 책임
- model detection boundary
- R01 / R02 / R03 / R04 동작
- canonical DetectedPII mapping
- provenance
- DetectionTier
- dependency failure semantics
- L3 / L4 ownership boundary
- frozen regression evidence 사용 범위

Production source 구현은 R5-S3 이후에 시작한다.

---

## 2. 계약 우선순위

LOCATION 구현 과정에서 계약 또는 과거 문서 사이에 충돌이 발생할 경우
다음 우선순위를 적용한다.

    1. src/privacy_proxy/schemas.py
    2. 현재 canonical runtime boundary
    3. FINAL L3/L4 ownership contract
    4. LOCATION v0.1.1 FINAL_FROZEN evidence
    5. 과거 working / pending 문서

`src/privacy_proxy/schemas.py`를 canonical data contract의
최상위 기준으로 사용한다.

LOCATION 구현을 이유로 `schemas.py`를 임의 변경하지 않는다.

현재 schema로 표현할 수 없는 새로운 필수 runtime 정보가 발견될 경우,
LOCATION 구현 내부에서 우회하지 않고 별도의 Schema Change Decision으로 처리한다.

---

## 3. Canonical Nine-Field Schema

LOCATION은 기존 canonical `DetectedPII`를 그대로 사용한다.

Canonical field는 다음 9개이다.

    segment_id
    start_idx
    end_idx
    entity_type
    confidence
    source
    tier
    original_value
    normalized

LOCATION canonical mapping은 다음과 같다.

    segment_id      = supplied request segment_id
    start_idx       = refined raw-coordinate start
    end_idx         = refined raw-coordinate end
    entity_type     = LOCATION
    confidence      = None
    source          = actual LOCATION producer.name
    tier            = MODEL
    original_value  = raw_prompt[start_idx:end_idx]
    normalized      = original_value

Presidio 또는 spaCy가 제공하는 numeric score를
canonical `confidence`로 복사하지 않는다.

현재 schema의 `extra="forbid"` 계약을 유지한다.

LOCATION 전용 실험 metadata를 canonical `DetectedPII`에 추가하지 않는다.

---

## 4. LOCATION Semantic Scope

L3 `LOCATION`은 정형 행정구역 기반 지명을 담당한다.

현재 구조적 범위는 다음과 같다.

    SIDO
    SIGUNGU
    EUPMYEONDONG

예:

    서울특별시
    경기도
    수원시
    영통구
    매탄동

L3 LOCATION은 다음 entity의 ownership을 가져오지 않는다.

    LOCATION_INFORMAL
    ADDRESS
    ADDRESS_ROAD
    ADDRESS_LOT
    ADDRESS_DETAIL

비정형·비공식 위치 표현은 L4 `LOCATION_INFORMAL`의 책임을 유지한다.

예:

    강남 쪽
    역삼 근처
    저희 동네

---

## 5. Detection Evidence

LOCATION의 detection evidence는 Korean spaCy NER model의
`LC` detection을 기준으로 한다.

Frozen reference:

    spaCy version           = 3.8.16
    ko_core_news_lg         = 3.8.0
    accepted NER label      = LC
    canonical entity        = LOCATION

Historical frozen evidence에서 다음이 확인되었다.

    Raw LC total            = 9
    Presidio LOCATION total = 9
    start matches           = 9 / 9
    end matches             = 9 / 9
    surface matches         = 9 / 9
    full span matches       = 9 / 9

이 frozen evidence는 새 runtime의 regression oracle로 사용한다.

Numeric model score 또는 Presidio score 자체는
canonical confidence 또는 DetectionTier의 근거가 아니다.

---

## 6. Producer Architecture

LOCATION dependency는 전역 AnalyzerEngine에 확장하지 않고
전용 L3 producer 내부에 격리한다.

목표 구조:

    raw_prompt
        |
        v
    LocationRecognizer
        |
        v
    ko_core_news_lg
        |
        v
    LC candidate
        |
        v
    R01 / R02 / R03 / R04
        |
        v
    RecognizerResult 0..N
        |
        v
    existing detection_adapter
        |
        v
    DetectedPII 0..N

현재 global AnalyzerEngine의 NoOp NLP boundary를
LOCATION 하나를 위해 전역 spaCy engine으로 변경하지 않는다.

LocationRecognizer capability:

    supported_language = ko
    supported_entity   = LOCATION

LocationRecognizer는 다른 entity type을 emit하지 않는다.

---

## 7. Registry / Provenance Boundary

현재 one-entity / one-producer registry 원칙을 유지한다.

LOCATION 구현 후에는 정확히 하나의 verified LOCATION producer가
registry에 존재해야 한다.

예상 producer count 변화:

    10 -> 11

LOCATION result는 기존 `resolve_producer()` provenance 검증을 통과해야 한다.

Canonical source 원칙:

    source = actual LOCATION producer.name

Historical `SpacyRecognizer` 이름을 현재 canonical source로
임의 하드코딩하지 않는다.

Recognizer metadata가 실제 등록된 producer identity와 충돌하면
fail closed 한다.

---

## 8. DetectionTier

LOCATION의 canonical DetectionTier는 다음으로 고정한다.

    DetectionTier.MODEL

Canonical mapping:

    tier = MODEL

그 이유는 LOCATION 존재 여부를 최초로 생성하는 evidence가
`ko_core_news_lg`의 NER model `LC`이기 때문이다.

R01과 R02는 이미 존재하는 model detection을 정제하는 단계다.

따라서 R01 또는 R02가 적용되더라도 tier는 MODEL을 유지한다.

다음 값은 tier 판정 근거로 사용하지 않는다.

    Presidio score
    spaCy numeric score
    임의 threshold 값 자체

---

## 9. R01 — Boundary Suffix Trim

Rule ID:

    R01_BOUNDARY_SUFFIX_TRIM

Frozen controlled suffix:

    에
    이고
    입니다

Model LOCATION token에 승인된 terminal suffix가 포함되어 있고,
suffix 제거 후 값이 승인된 행정구역 형태를 만족하면
해당 terminal suffix만 제거한다.

예:

    Raw model span:
    경기도에

    Final LOCATION:
    경기도

Canonical result:

    start_idx       = refined raw-coordinate start
    end_idx         = refined raw-coordinate end
    original_value  = raw_prompt[start_idx:end_idx]
    normalized      = original_value

임의 substring trimming은 허용하지 않는다.

---

## 10. R02 — Compound Administrative Decomposition

Rule ID:

    R02_COMPOUND_ADMIN_DECOMPOSITION

하나의 model LOCATION span 안에
공백으로 분리된 복수의 승인된 행정구역 단위가 존재하면
각 행정구역 단위를 별도 LOCATION result로 emit한다.

예:

    Raw model candidate:
    경기도 수원시 영통구에

Final result:

    LOCATION 경기도
    LOCATION 수원시
    LOCATION 영통구

허용되는 변환:

    1 raw model candidate
        ->
    N RecognizerResult
        ->
    N DetectedPII

각 final result는 자신의 raw-prompt 좌표를 사용한다.

R02는 다음을 수행하지 않는다.

    missing parent inference
    hierarchy validation
    hierarchy repair

---

## 11. R03 — Ambiguous Compound Rejection

Rule ID:

    R03_AMBIGUOUS_COMPOUND_REJECTION

예:

    경기도수원시영통구
    수원시영통구
    부산광역시해운대구

공백 없이 연결된 multi-level administrative token은
자동 분해하지 않는다.

Runtime behavior:

    candidate rejection
    RecognizerResult emission = 0
    exception = none

R03은 정상적인 graceful detection rejection이다.

R03을 dependency failure 또는 `L3RuntimeError`로 승격하지 않는다.

---

## 12. R04 — Unsupported Token Rejection

Rule ID:

    R04_UNSUPPORTED_TOKEN_REJECTION

승인된 LOCATION refinement 규칙으로 처리할 수 없는 token은
LOCATION으로 emit하지 않는다.

Frozen example:

    영통구에서
    강남구였으며

Runtime behavior:

    candidate rejection
    RecognizerResult emission = 0
    exception = none

R04는 정상적인 graceful detection rejection이다.

R04는 dependency failure가 아니다.

---

## 13. Detector-Miss Boundary

LocationRecognizer는 model이 탐지하지 않은 LOCATION을
새로 생성하지 않는다.

금지 동작:

    model miss
        ->
    rule 또는 normalizer가 새로운 LOCATION 생성

Historical B08 partial miss는 그대로 관찰 가능해야 한다.

Frozen requirement:

    B08 EXPECTED_LIMITATION

B08에서 model이 제공하지 않은 행정구역을
normalizer가 임의 생성하지 않는다.

---

## 14. Historical Administrative Metadata

Historical LOCATION normalizer에서는 내부적으로 다음 값을 생성했다.

    admin_type
    detail_level
    normalization_rule
    removed_suffix

구조적 분류 예:

    SIDO
    SIGUNGU
    EUPMYEONDONG

    SI
    GUN
    GU
    EUP
    MYEON
    DONG

그러나 이 값들은 현재 canonical nine-field `DetectedPII`에 포함되지 않는다.

현재 LOCATION runtime에서는 다음 목적으로만 사용할 수 있다.

    LocationRecognizer internal decision
    unit-test evidence
    formal evaluation evidence
    controlled fixture evidence

다음 값을 canonical DetectedPII에 추가하지 않는다.

    admin_type
    detail_level
    normalization_rule
    removed_suffix

L5 또는 공통 pipeline이 실제 runtime interface에서
이 metadata를 필요로 한다는 새로운 요구가 발생할 경우
별도 Schema Change Decision을 연다.

---

## 15. normalized Field

현재 LOCATION canonical mapping:

    normalized = original_value

여기서 normalized는 전국 행정구역 DB 또는 gazetteer의
canonical lookup result를 의미하지 않는다.

현재 범위에 포함되지 않는 기능:

    nationwide administrative gazetteer
    administrative existence validation
    parent inference
    parent-child hierarchy validation
    invalid hierarchy repair
    administrative code conversion

Historical normalizer는 morphological / structural refinement이며
gazetteer-based existence validator가 아니다.

---

## 16. Raw Coordinate Invariant

모든 canonical LOCATION result는 다음을 만족해야 한다.

    raw_prompt[start_idx:end_idx] == original_value

좌표 기준은 항상 canonical `ProxyContext.raw_prompt`이다.

다음 좌표를 canonical coordinate로 사용하지 않는다.

    transformed string coordinate
    spaCy-internal normalized coordinate
    token reconstruction coordinate

Raw coordinate integrity가 normalization coverage보다 우선한다.

---

## 17. Adapter Boundary

기존 common `detection_adapter.py`의 역할은 유지한다.

    1 RecognizerResult
        ->
    1 DetectedPII

LOCATION 전용 R01 / R02 / R03 / R04 동작은
common adapter 이전의 producer boundary에서 처리한다.

특히 R02의 one-to-many decomposition 때문에
common adapter의 return contract를 변경하지 않는다.

LocationRecognizer가 필요한 개수의 final RecognizerResult를 생성하고,
기존 adapter가 각각의 result를 DetectedPII로 변환한다.

---

## 18. Dependency Failure

다음 상태는 정상적인 zero-detection이 아니다.

    ko_core_news_lg missing
    ko_core_news_lg load failure
    required LC capability missing
    model inference failure
    unexpected model/runtime exception

이 상태를 다음처럼 처리해서는 안 된다.

    dependency failure
        ->
    return []
        ->
    pretend LOCATION was absent

Dependency/runtime failure는 기존 L3 fail-closed boundary를 따른다.

Sensitive dependency exception text를 외부 오류 메시지에
그대로 노출하지 않는다.

다음 두 종류의 상태를 명확히 구분한다.

    R03 / R04
        = graceful candidate rejection

    dependency/model failure
        = runtime failure

Model loading을 initialization 시점에 할지 lazy runtime에 할지는
구현 단계에서 결정할 수 있다.

어느 경우에도 dependency failure를 성공적인 empty result로 위장하지 않는다.

---

## 19. Model Version Boundary

Frozen reference model:

    ko_core_news_lg = 3.8.0
    spaCy           = 3.8.16

새 runtime은 frozen reference behavior를 우선 regression 검증한다.

Model version의 silent upgrade는 허용하지 않는다.

Model version이 변경될 경우 LOCATION frozen evidence와의
regression을 다시 확인해야 한다.

Dependency packaging / installation mechanism은
R5-S3 이후 별도 검증한다.

---

## 20. L3 / L4 Boundary

Ownership은 다음과 같이 유지한다.

    L3 = LOCATION
    L4 = LOCATION_INFORMAL

L3 LOCATION은 structured administrative geographic unit을 담당한다.

L4 LOCATION_INFORMAL은 informal / non-administrative location expression을
담당한다.

L3 LocationRecognizer는 L4 output semantics를 가져오지 않는다.

L3/L4 overlap 또는 winner algorithm은
LOCATION producer의 책임이 아니다.

Competing result를 LocationRecognizer 내부에서 임의 suppression하지 않는다.

---

## 21. ADDRESS Boundary

LOCATION 구현은 ADDRESS를 구현하거나 재정의하지 않는다.

별도 entity:

    ADDRESS
    ADDRESS_ROAD
    ADDRESS_LOT
    ADDRESS_DETAIL

LOCATION 개발 중 full-address detection으로 범위를 확장하지 않는다.

ADDRESS는 별도 runtime implementation phase에서 처리한다.

---

## 22. Frozen Regression Oracle

Historical frozen artifacts는 수정하지 않는다.

새 LOCATION runtime은 frozen evidence를 regression oracle로 사용한다.

### L01-L08 binding

Expected:

    9 / 9 full LC -> LOCATION span preservation

### Controlled Normalizer

Historical expectation:

    Raw LOCATION spans = 9
    Normalized units   = 15
    R01 units          = 6
    R02 units          = 9
    Exact recovery     = 15 / 15

### B01-B08 v0.1.1

Frozen outcomes:

    B01 GRACEFUL_REJECTION
    B02 GRACEFUL_REJECTION
    B03 GRACEFUL_REJECTION
    B04 GRACEFUL_REJECTION
    B05 GRACEFUL_REJECTION
    B06 STRUCTURAL_SUCCESS
    B07 STRUCTURAL_SUCCESS
    B08 EXPECTED_LIMITATION

Frozen aggregate:

    STRUCTURAL_SUCCESS          = 2
    EXPECTED_LIMITATION         = 1
    UNDERSEGMENTED_FALSE_ACCEPT = 0
    GRACEFUL_REJECTION          = 5
    UNHANDLED_EXCEPTION         = 0

Historical frozen artifacts 자체는 새 runtime 구현을 위해 수정하지 않는다.

---

## 23. Current Pre-Implementation Runtime Gap

Authoritative R5-S2 baseline에서는 다음이 아직 구현되지 않았다.

    LOCATION registry mapping = absent
    LOCATION tier mapping     = absent
    current runtime ko_core_news_lg dependency = absent

이는 정상적인 pre-implementation 상태다.

R5-S2에서는 이 상태를 변경하지 않는다.

---

## 24. Explicit Non-Goals

R5-S2는 다음 변경을 승인하지 않는다.

    schemas.py modification
    common detection_adapter specialization
    global AnalyzerEngine spaCy migration
    LOCATION_INFORMAL implementation
    ADDRESS implementation
    nationwide gazetteer construction
    hierarchy repair
    confidence calculation
    score-to-confidence conversion
    L3/L4 overlap winner policy
    L5 risk-policy modification
    historical frozen artifact modification

---

## 25. R5-S2 Exit Criteria

R5-S2 완료 조건:

    contract status = PROVISIONAL
    schemas.py authority documented
    canonical nine-field mapping documented
    confidence = None
    tier = MODEL
    actual producer provenance documented
    R01 semantics documented
    R02 one-to-many semantics documented
    R03 graceful rejection documented
    R04 graceful rejection documented
    detector miss non-recovery documented
    dependency fail-closed semantics documented
    L3/L4 boundary documented
    ADDRESS non-expansion documented
    LOCATION-only metadata internal-only rule documented
    frozen regression oracle documented
    production source unchanged
    tests unchanged

---

## 26. Next Phase

R5-S2 완료 후 다음 단계:

    R5-S3 — LOCATION Runtime Test Matrix

R5-S3에서는 구현 전에 최소 다음 test family를 정의한다.

    canonical schema
    registry
    provenance
    tier
    R01
    R02
    R03
    R04
    model-miss preservation
    dependency failure
    L01-L08 frozen regression
    B01-B08 frozen regression
    mixed-entity behavior
    unrequested-result isolation
    L3/L4 ownership
    ADDRESS non-expansion

R5-S3가 adjudication 되기 전에는
production LOCATION implementation을 시작하지 않는다.
