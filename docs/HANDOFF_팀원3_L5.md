# 팀원3 L5 인수인계

최종 갱신: 2026-10-22 (KST)

## 현재 작업 상태

- 작업 폴더: `privacy-proxy-l5-anchor`, 브랜치: `codex/l5-anchor-priority`.
- 통합 기준: PR #57이 머지된 `develop`의 `93fd640`. L4 번호 앵커 전달과 계좌번호 앵커 전달을 포함한다.
- 아래 변경은 L5 resolver와 관련 테스트·문서만 대상으로 한다. L4 생산자, 공통 스키마, L6 구현은 수정하지 않았다. 최종 머지 여부는 GitHub PR 및 develop 이력으로 확인한다.
- 관련 테스트 266개 통과. 전체 E2E는 21개 중 18개 통과, 한국어 이름 3개 실패. 전체 완료로 간주하면 안 된다.

## 역할과 계약

L5는 탐지 구간 검증 → 중첩 후보 선택 → 위험 점수 및 항목별 정책 결정을 담당한다. 원문 치환·복원 매핑은 L6 담당이다.

공통 기준은 `src/privacy_proxy/schemas.py`의 EntityType과 DetectedPII이다. L3 13종 + L4 14종으로 총 27종을 지원한다. 예전 PHONE/EMAIL/RRN 등의 이름으로 자동 보정하지 않으며 미지원 타입은 실패 처리한다.

start_idx/end_idx는 전체 raw_prompt의 반개구간 좌표이다. confidence는 필수지만 None일 수 있고 tier는 필수이다. 선택적 anchor_text/start/end는 함께 존재하거나 모두 None이다. L4는 세그먼트 로컬 좌표를 내고 adapter가 값과 앵커 모두에 offset_base를 한 번 더한다.

## 이번에 변경한 후보 선택 규칙

### 직접 연결 확인

`risk/resolver.py`의 `has_direct_anchor()`는 앵커와 값이 실제 원문 조각과 일치하는지 확인한 다음 사이 문자열을 본다. 앞쪽은 가로 공백·조사(은/는/이/가/의)·콜론(전각 포함)/등호, 뒤쪽은 가로 공백·조사(은/는/이/가)를 허용한다. 최대 간격은 `_MAX_DIRECT_ANCHOR_GAP=6`이다. 줄바꿈·설명 문장·중간 숫자는 직접 연결이 아니다. L5가 새 앵커를 검색하지는 않는다.

### 면허 충돌 예외 — 선택 이유가 최종 결과에 남도록 수정

동일 segment_id와 동일 값 구간에 KR_DRIVER_LICENSE와 직접 연결된 L4 RULE_ANCHORED 번호가 함께 있어야 한다. 대상은 ORDER_ID, TRACKING_NUMBER, CUSTOMER_ID, ACCOUNT_NUMBER이다.

예외를 적용하면 면허 후보와 직접 연결 근거 없는 동급 이하 번호 후보를 제외한다. 예를 들어 `송장번호는 별도입니다. 주문번호: 112412345601`에 면허 후보까지 들어온 경우, 주문번호 근거로 면허를 제외하고 나서 송장번호가 대신 승리하던 문제를 방지한다. 면허가 없는 모든 번호 간 충돌을 해결하는 일반 규칙은 아니다. 부분 겹침에는 예외를 적용하지 않는다. 주민번호 등 다른 deterministic 후보와 기존 보호 구간 검사는 유지한다.

### JSON 동률 비교 제거

전체 model_dump_json 문자열로 승자를 고르지 않는다. tier·보호 분류·길이·타입·출처를 먼저 비교하며 같은 그룹에서는 검증된 직접 연결 여부를 confidence보다 먼저 비교한다. 뒤에는 명시된 원문/정규화/좌표/앵커 필드만 사용한다.

confidence는 출처가 명확하고 같은 source·type·tier 그룹의 모든 점수가 산정된 경우에만 비교한다. unknown/빈 출처 또는 그룹 내 None이 있으면 점수 크기를 비교하지 않는다.

그 밖의 명시적 조건이 전부 같고 비교 불가능한 confidence만 다르면 ValueError로 실패한다. 점수를 임의로 합치거나 None으로 덮어쓰지 않는다. 완전히 동일한 중복은 하나로 정리하며, 이미 강한 후보에 가려진 중복이나 서로 다른 세그먼트는 이 실패를 유발하지 않는다.

실패 시 `risk/stage.py`가 `L5_VALIDATION_FAILED`를 반환하고 입력 탐지 목록을 보존한다. 파이프라인은 L6/L7으로 진행하지 않는다. 원문을 그대로 외부에 보내는 처리가 아니다. 모호한 중복 입력은 이전과 달리 요청 실패가 될 수 있다는 운영 영향이 있다.

## 현재 항목별 정책

- 직접·서비스 식별자와 민감정보: TOKENIZE.
- PRODUCT_ITEM: QI 점수와 무관하게 GENERALIZE. L6에서 “상품”으로 일반화하고 상품명을 복원 매핑에 저장하지 않는다.
- PURCHASE_PATTERN: 위험 점수에는 반영하지만 ALLOW. 원문 유지, 복원 매핑 없음.
- 나머지 QI: 직접/서비스 식별자의 최소 점수 적용 전 QI 점수가 30점 이상이면 GENERALIZE, 미만이면 ALLOW.
- 요청 단위 policy_action과 항목별 entity_policies는 다를 수 있다. L6는 항목별 정책을 전달받는다.
- 요청 점수는 직접식별자 최소 80, 서비스 식별자 최소 85. 민감정보는 최대 confidence × 80이며 미산정이 있으면 80을 적용한다. 민감정보 0점도 TOKENIZE한다.

## 수정 파일과 검증 근거

| 파일 | 역할 |
|---|---|
| `src/privacy_proxy/risk/resolver.py` | 직접 연결, 면허 충돌 예외, 명시적 동률 비교와 모호한 점수 실패 처리 |
| `tests/unit/test_anchor_priority.py` | 연결 양성/음성, 다른 등급·세그먼트·부분 겹침 |
| `tests/unit/test_resolver_tie_breaks.py` | 세 결함 회귀, 순열, 중복 점수 및 실패 시 입력 보존 |
| `tests/integration/test_l5_stage.py` | 실제 L4 네 종류 인식기, 전역 offset, L5 선택 및 TOKENIZE |
| `tests/integration/test_nullable_contract.py` | 모호한 점수 동률의 기대값을 실패로 변경 |
| `docs/status/11_L5_anchor_priority.md` | 세부 구현 및 머지/검증 경과 |
| `docs/reviews/2026-10-21-merged-l4-e2e.json` | 전체 E2E 결과 원본 |

[설계 결정](decisions/0005-l5-anchor-priority-and-explicit-ties.md)과 [상세 상태](status/11_L5_anchor_priority.md)를 함께 참고한다. 이전 9월 인수인계의 18종 지원·민감정보 옛 타입·mock L5 교체 예정·80개 테스트 기록은 현재 상태가 아니다.

## 재현 방법

저장소 루트에서 테스트 환경의 Python으로 실행한다. 이 작업에서 사용한 환경은 `/private/tmp/l5-anchor-check/bin/python`이며 임시 환경이므로 다른 머신에서는 프로젝트 의존성을 별도로 준비해야 한다. L4 이메일 가드는 presidio-analyzer 2.2.364, tldextract 5.3.2, regex 2026.9.3을 요구한다.

```sh
python -m pytest tests/unit/test_resolver_tie_breaks.py tests/unit/test_anchor_priority.py tests/unit/test_overlap_resolver.py tests/unit/test_risk_score.py tests/integration/test_l5_stage.py tests/unit/l4/test_recognizers.py tests/unit/test_l4_adapter.py tests/integration/test_nullable_contract.py tests/integration/test_entity_policies.py tests/test_e2e_validation.py tests/test_pipeline.py tests/integration/test_l4_pipeline_regressions.py
python e2e_leak_test.py --scope all --report /tmp/l5-e2e.json
```

전체 E2E는 spaCy 3.8.16과 ko_core_news_lg/en_core_web_lg 3.8.0이 필요하다. 외부 LLM HTTP는 echo로 대체한다. 단위/통합 테스트에는 L3 스텁도 있으므로 전체 모델 기반 E2E와 구분한다.

## 2026-10-22 문서 갱신 시 재확인

설명한 로직이 코드에 반영되어 있음을 확인하고 최대 간격 6자를 이름 있는 상수로 정리했다. 핵심 앵커·동률 테스트 33개를 재실행해 통과했다. 전체 266개는 직전 통합 검증 결과이며, 이번 전체 재실행은 import 단계 지연으로 중단했다. 이전 전체 통과 기록과 이번 실행 결과를 구분한다.

## 남은 작업

1. 한국어 이름 NER 모델 경로를 제공하고 `L4_NER_ENABLED`를 활성화한 뒤 E2E name_1/name_2/name_3을 재검증한다. 현재 환경은 비활성화·경로 미설정이어서 세 이름이 탐지되지 않았다.
2. L4 담당자와 최대 6자 연결 규칙 및 동일 근거/상이한 confidence 후보가 발생할 수 있는지 확인한다. 코드를 검증한 것과 담당자 합의는 별개이며, 직접 전달하거나 합의했다고 기록하지 않는다.
3. 복수의 직접 앵커가 서로 다른 타입을 지지하는 경우 현재는 기존 고정 타입/출처 순서로 선택한다. 의미상 우선순위 확대가 필요하면 별도 정책과 테스트를 추가한다.
4. 후속 수정은 develop의 최신 상태에서 시작하고, 이 문서의 E2E 실패 3건을 해결 전까지 통과로 간주하지 않는다.
