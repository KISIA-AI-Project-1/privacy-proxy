# L5 QI 위험도 평가 결정사항

> 기준일: 2026-09-07  
> 범위: 현재 지원 완료 엔터티와 L5 로직은 준비됐지만 L4 출력 연동을 기다리는 엔터티를 구분한다.

## 1. L5 책임

L5는 탐지된 정보를 직접 마스킹하지 않는다. 위험도와 처리 정책만 결정하고 실제 치환은 L6가 담당한다.

```text
L3/L4 엔터티 탐지
  → L5 분류·위험도 계산·정책 결정
  → L6 토큰화·일반화·통과
```

## 2. L4-L5 공통 엔터티 계약

`SERVICE_IDENTIFIER`는 프로젝트 내부 운영 분류이며, 개인정보 보호법의 `고유식별정보`를 뜻하지 않는다.

| L4 `entity_type` | L5 운영 분류 | 처리 | 상태 |
|---|---|---|---|
| `PERSON` | `DIRECT_IDENTIFIER` | 최소 80점, `TOKENIZE` | 지원 |
| `ADDRESS_TAIL` | `DIRECT_IDENTIFIER` | 최소 80점, `TOKENIZE` | 지원 |
| `LOCATION_INFORMAL` | `QUASI_IDENTIFIER` | 상세도·결합 평가 | 지원 |
| `ORDER_ID` | `SERVICE_IDENTIFIER` | 최소 85점, `TOKENIZE` | 지원 |
| `TRACKING_NUMBER` | `SERVICE_IDENTIFIER` | 최소 85점, `TOKENIZE` | 지원 |
| `CUSTOMS_CLEARANCE_ID` | `SERVICE_IDENTIFIER` | 최소 85점, `TOKENIZE` | 지원 |
| `CUSTOMER_ID` | `SERVICE_IDENTIFIER` | 최소 85점, `TOKENIZE` | 지원 |
| `SENSITIVE_HEALTH` | `SENSITIVE_INFORMATION` | confidence 반영 | 부분 지원 |
| `SENSITIVE_RELIGION` | `SENSITIVE_INFORMATION` | confidence 반영 | 부분 지원 |
| `SENSITIVE_FAMILY` | `SENSITIVE_INFORMATION` | confidence 반영 | 부분 지원 |
| `SENSITIVE_FINANCIAL` | `SENSITIVE_INFORMATION` | confidence 반영 | 부분 지원 |
| `AGE`, `AGE_GROUP` | `QUASI_IDENTIFIER` | 연령 상세도·결합 평가 | L4 연동 대기 |
| `GENDER` | `QUASI_IDENTIFIER` | 기본 점수 5 | L4 연동 대기 |
| `PRODUCT`, `PRODUCT_NAME`, `PURCHASED_PRODUCT` | `QUASI_IDENTIFIER` | 상품 희귀성·결합 평가 | L4 연동 대기 |
| `DATE_TIME`, `DATETIME`, `PURCHASE_TIME`, `ORDER_TIME` | `QUASI_IDENTIFIER` | 기본 점수 12·결합 평가 | L4 연동 대기 |
| `PRICE`, `AMOUNT` | `QUASI_IDENTIFIER` | 기본 점수 8 | L4 연동 대기 |
| `REFUND_REASON` | `QUASI_IDENTIFIER` | 기본 점수 10 | L4 연동 대기 |
| `PURCHASE_COUNT` | `QUASI_IDENTIFIER` | 기본 점수 6 | L4 연동 대기 |

L3에서 탐지하는 이름·전화번호·이메일·주소·주민등록번호 등의 기존 공통 타입은 기존 L5 매핑을 유지한다.

## 3. 위험도 등급과 처리 정책

| 점수 | 등급 |
|---:|---|
| 0 이상 30 미만 | `LOW` |
| 30 이상 60 미만 | `MEDIUM` |
| 60 이상 | `HIGH` |

| 조건 | `policy_action` |
|---|---|
| 직접식별자 또는 서비스 식별자 | `TOKENIZE` |
| 민감정보 후보 | confidence는 점수에 반영하되 보호 우선으로 `TOKENIZE` |
| QI만 있고 최종 등급이 `MEDIUM`/`HIGH` | `GENERALIZE` |
| 그 외 | `ALLOW` |

## 4. 민감정보 confidence 반영

L4는 민감정보 4종을 confidence `0.3~0.5`의 후보로 제공한다. L5는 이 값을 다음과 같이 점수에 반영한다.

```text
민감정보 점수 = 80 × confidence
```

| confidence | 점수 | 등급 | 처리 |
|---:|---:|---|---|
| 0.3 | 24 | `LOW` | `TOKENIZE` |
| 0.4 | 32 | `MEDIUM` | `TOKENIZE` |
| 0.5 | 40 | `MEDIUM` | `TOKENIZE` |
| 1.0 | 80 | `HIGH` | `TOKENIZE` |

민감정보 후보가 여러 개면 가장 높은 confidence를 사용한다. QI 점수가 더 높으면 기존 QI 점수를 유지한다.

## 5. 지역 QI

| 지역 수준 | 기본 점수 | 구체성 |
|---|---:|---:|
| 시·도 | 5 | 1 |
| 시·군·구 | 15 | 2 |
| 읍·면·동·리·가 | 22 | 3 |
| 상세도 판단 불가 | 5 | 0 |

### 5.1 중복 제거

현재는 문자열이 같은 지역만 중복 제거하고 서로 다른 지역은 모두 유지한다.

```text
영통구 + 영통구 → 영통구 하나만 계산
서울특별시 + 영통구 → 둘 다 유지
경기도 + 수원시 + 영통구 → 현재는 세 지역 모두 유지
```

향후 Location Normalizer가 상·하위 관계를 확인할 수 있을 때만 가장 구체적인 지역으로 축약한다.

### 5.2 QI 결합 가산점

| 중복 제거 후 QI 개수 | 가산점 |
|---:|---:|
| 0~1개 | 0 |
| 2개 | 8 |
| 3개 | 12 |
| 4개 | 16 |

### 5.3 L4 연동 대기 QI 점수

아래 로직과 단위 테스트는 L5에 준비되어 있지만, 현재 L4가 해당 엔터티를 출력하지 않으므로
통합 파이프라인에서 지원 완료로 보지 않는다.

| QI | 기본 점수 | 비고 |
|---|---:|---|
| 정확 연령 (`AGE`, `37세`) | 20 | 정확 연령으로 판별 |
| 연령대 (`AGE_GROUP` 등) | 8 | 정확 연령이 아닌 연령 정보 |
| 희귀 상품 | 18 | `한정판`, `희귀`, `리미티드`, `limited`, `단종` 포함 |
| 일반 상품 | 5 | 희귀 상품 키워드 없음 |
| 날짜·구매·주문 시각 | 12 | 시간 계열 별칭을 동일 QI로 중복 제거 |
| 성별 | 5 | - |
| 가격·금액 | 8 | 두 타입을 각각 지원 |
| 환불 사유 | 10 | - |
| 구매 횟수 | 6 | 초기 실험값 |

특별 결합 규칙은 다음과 같다.

| 조합 | 추가 점수 | 사유 기록 |
|---|---:|---|
| 정확 연령 + 세부 지역 | 17 | 재식별 가능성 증가 |
| 정확 시각 + 세부 지역 | 8 | 시각·지역 결합 |
| 희귀 상품 + 세부 지역 | 0 | 결합 사실을 위험 사유에 기록 |

## 6. 현재 실행 상태와 L4 연동 대기

현재 L4가 실제로 제공하는 준식별자는 `LOCATION_INFORMAL`이 중심이다. 그러므로 현재
연동 상태만으로는 연령·상품·시간·금액 등을 함께 사용하는 완전한 QI 조합 위험도를
계산할 수 없다.

다음 타입의 L5 분류·점수·결합 로직과 단위 테스트는 구현해 두었지만, L4가 탐지값을
제공하지 않아 **L4 연동 대기** 상태이다.

- `AGE`, `AGE_GROUP`
- `PRODUCT`, `PRODUCT_NAME`, `PURCHASED_PRODUCT`
- `DATE_TIME`, `DATETIME`, `PURCHASE_TIME`, `ORDER_TIME`
- `GENDER`
- `PRICE`, `AMOUNT`
- `REFUND_REASON`
- `PURCHASE_COUNT`

L4가 이 타입을 제공하기 전까지는 실제 운영 점수에 반영되지 않는다.

## 7. 출력

L5는 `ProxyContext`에 다음 값을 기록한다.

```json
{
  "risk_score": 32.0,
  "risk_level": "MEDIUM",
  "risk_reasons": [
    "민감정보 후보(SENSITIVE_HEALTH, confidence=0.40)가 포함됨"
  ],
  "policy_action": "TOKENIZE"
}
```

L5는 원문을 변경하지 않는다. L6가 `policy_action`을 읽고 실제 처리를 수행한다.

## 8. 현재 한계

- `LOCATION_INFORMAL`은 거주지·근무지·배송지 역할을 구분하지 못한다.
- 행정구역 상·하위 관계와 충돌 상태를 자동으로 검증하지 못한다.
- 민감정보는 L4가 제공한 confidence를 사용하지만, 문맥·부정·정보 주체를 재판정하지는 못한다.
- L4 연동 대기 QI는 L5 단위 테스트만 완료됐으며 실제 L4→L5 통합 동작은 미검증이다.
