# L5 QI 위험도 평가 결정사항

> 기준일: 2026-09-26

## 1. 적용 범위

L5는 공통 `EntityType` 19종 중 `ETC`를 제외한 18종만 평가한다. 현재 준식별자로 분류되는
타입은 `LOCATION_INFORMAL`이다. 새 타입은 공통 스키마 합의 없이 L5에 독자적으로 추가하지
않는다.

## 2. 보호 분류와 정책

| 분류 | EntityType | 정책 |
|---|---|---|
| 직접식별자 | `PHONE`, `EMAIL`, `RRN`, `PERSON_KO`, `ACCOUNT_NUMBER`, 주소 3종 | `TOKENIZE` |
| 서비스 식별자 | `BUSINESS_REGISTRATION_NUMBER`, `CUSTOMS_CLEARANCE_ID`, `ORDER_ID`, `TRACKING_NUMBER`, `CUSTOMER_ID` | `TOKENIZE` |
| 준식별자 | `LOCATION_INFORMAL` | 상세도·반복·결합 평가 |
| 민감정보 | `SENSITIVE_HEALTH`, `SENSITIVE_RELIGION`, `SENSITIVE_FAMILY`, `SENSITIVE_FINANCIAL` | confidence 반영 후 `TOKENIZE` |
| 미분류 | `ETC` | fail-closed |

주소 3종은 `ADDRESS_ROAD`, `ADDRESS_LOT`, `ADDRESS_DETAIL`이다.

## 3. 현재 운영 점수

| 조건 | 점수·처리 |
|---|---|
| 직접식별자 포함 | 최소 80점, `HIGH`, `TOKENIZE` |
| 서비스 식별자 포함 | 최소 85점, `HIGH`, `TOKENIZE` |
| 민감정보 후보 포함 | `80 × 최대 confidence`, `TOKENIZE` |
| QI만 있고 30점 이상 | `GENERALIZE` |
| 그 외 | `ALLOW` |

등급 경계는 다음과 같다.

| 점수 | 등급 |
|---:|---|
| 0 이상 30 미만 | `LOW` |
| 30 이상 60 미만 | `MEDIUM` |
| 60 이상 | `HIGH` |

## 4. LOCATION_INFORMAL 점수

| 지역 수준 | 기본 점수 |
|---|---:|
| 시·도 | 5 |
| 시·군·구 | 15 |
| 읍·면·동·리·가 | 22 |
| 상세도 판단 불가 | 5 |

동일한 지역 값은 한 번만 계산한다. 서로 다른 지역 값 2개는 8점, 3개는 12점의 결합
가산점을 적용한다. 행정구역 상하위 관계를 검증하는 normalizer가 없으므로 서로 다른 문자열을
임의로 하나로 합치지 않는다.

## 5. 민감정보 후보

민감정보 4종은 L4 구현 예정이며 `CANDIDATE` tier와 낮은 confidence를 사용할 수 있다.

```text
민감정보 점수 = 80 × confidence
```

confidence가 낮아도 보호 우선으로 `TOKENIZE`한다.

confidence 필드는 필수이며 null은 미산정을 뜻한다. 민감정보 후보 중 하나라도 null이면
정책상 보수적 대체 점수 80을 사용하고 미산정 사유를 기록한다. 실제 confidence 값은
변경하지 않는다. 0.0은 미산정이 아니므로 기존 0점·TOKENIZE 동작을 유지한다.
직접·서비스 식별자와 지역 QI는 null이어도 기존 운영 점수 규칙을 사용한다.

## 6. 한계

- 현재 공통 스키마에는 서로 독립적인 QI 범주가 하나뿐이어서 “QI 3종 결합” 규칙을 실제로
  평가할 수 없다.
- 위치 행정계층 normalizer와 실제 모집단 희소성 통계가 없다.
- 현재 점수와 임계값은 PoC 초기값이며 법률 기준이 아니다.
- L5는 정책만 결정하며 실제 치환은 L6가 수행한다.
