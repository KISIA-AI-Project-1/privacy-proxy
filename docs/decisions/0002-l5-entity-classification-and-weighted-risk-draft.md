# L5 엔터티 분류와 가중 위험 점수 초안

> 상태: PROPOSED
> 기준 스키마: `src/privacy_proxy/schemas.py`의 `EntityType`

## 1. 대상

공통 스키마 19종 중 `ETC`를 제외한 18종만 계산한다. `ETC`와 공통 enum 밖의 문자열은
fail-closed 처리한다.

## 2. 분류

- `DIRECT_IDENTIFIER`: `PHONE`, `EMAIL`, `RRN`, `PERSON_KO`, `ACCOUNT_NUMBER`,
  `ADDRESS_ROAD`, `ADDRESS_LOT`, `ADDRESS_DETAIL`
- `SERVICE_IDENTIFIER`: `BUSINESS_REGISTRATION_NUMBER`, `CUSTOMS_CLEARANCE_ID`,
  `ORDER_ID`, `TRACKING_NUMBER`, `CUSTOMER_ID`
- `QUASI_IDENTIFIER`: `LOCATION_INFORMAL`
- `SENSITIVE_INFORMATION`: 민감정보 4종

`ACCOUNT_NUMBER`는 L5 `DIRECT_IDENTIFIER`로 확정한다. 이는 법률상 분류 선언이 아니라 보호
누락을 막기 위한 운영 분류다.

## 3. 가중식

```text
R = 100 × (0.35 × I + 0.45 × S + 0.20 × C)
```

- `I`: 식별가능성
- `S`: 노출 피해 민감도
- `C`: 결합위험

현재 가중치는 실증 연구에서 직접 도출된 계수가 아니라 팀의 초기 정책 가설이다. 실제
fixture와 오탐·미탐 결과로 보정하기 전까지 운영 `assess_risk()`와 분리한다.

## 4. 정책 guard

```python
if has_direct_or_service_or_sensitive:
    action = "TOKENIZE"
elif risk_score >= 30:
    action = "GENERALIZE"
else:
    action = "ALLOW"
```

현재 QI는 `LOCATION_INFORMAL` 한 범주뿐이므로 독립 QI 3종 결합은 계산할 수 없다. 새로운
QI가 공통 `EntityType`에 추가되기 전에는 미래 확장 규칙으로만 유지한다.

## 5. 적용 형태

```python
from privacy_proxy.risk.weighted_score import calculate_weighted_risk

result = calculate_weighted_risk(context.detected_entities)
context.risk_score = result.score
context.risk_reasons = list(result.reasons)
context.policy_action = result.action
```

## 6. 검증 전 체크리스트

- [x] 공통 `EntityType`과 L5 allowlist 분리
- [x] `ETC` fail-closed
- [x] 지원 18종 분류·가중치 커버리지 테스트
- [ ] 실제 L3/L4 fixture 기반 캘리브레이션
- [ ] 가중치와 30/60 임계값 승인
- [ ] L5→L6 span별 정책 계약
