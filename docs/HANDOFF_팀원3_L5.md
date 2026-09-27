> **2026-09-27 계약 변경:** 현재 스키마·L5 지원은 L3 13종 + L4 14종 = 27종입니다. 이전 이름 4개와 ETC는 제거했고 연령 QI를 지원합니다. 아래 내용은 변경 전 기록이며 [최신 계약](status/09_L3_13종_스키마_반영.md)을 우선 참고하세요.

# 팀원3 L5 인수인계

> 최종 갱신: 2026-09-26 (KST)

## 역할

L5는 L3/L4 탐지 결과를 받아 중복·중첩을 정리하고 위험 점수, 위험 등급, 처리 정책을
결정한다. 원문 치환은 L6가 담당한다.

```text
L3/L4 → span 검증 → overlap resolver → assess_risk → L6
```

## 공통 엔터티 계약

`src/privacy_proxy/schemas.py`의 `EntityType`이 단일 기준이다.

- 공통 enum: 19종
- L5 지원: `ETC` 제외 18종
- `ETC` 및 enum 밖 문자열: fail-closed
- 타입명 별칭·대소문자 자동 보정 없음

세부 목록은 `docs/status/06_공통_엔터티_통합_구현_현황.md`를 참고한다.

## L5 분류

| 분류 | 타입 |
|---|---|
| 직접식별자 | `PHONE`, `EMAIL`, `RRN`, `PERSON_KO`, `ACCOUNT_NUMBER`, 주소 3종 |
| 서비스 식별자 | `BUSINESS_REGISTRATION_NUMBER`, `CUSTOMS_CLEARANCE_ID`, `ORDER_ID`, `TRACKING_NUMBER`, `CUSTOMER_ID` |
| 준식별자 | `LOCATION_INFORMAL` |
| 민감정보 | `SENSITIVE_HEALTH`, `SENSITIVE_RELIGION`, `SENSITIVE_FAMILY`, `SENSITIVE_FINANCIAL` |

## 주요 코드

| 파일 | 역할 |
|---|---|
| `src/privacy_proxy/schemas.py` | 공통 enum과 Pydantic 계약 |
| `src/privacy_proxy/risk/entity_contract.py` | L5 지원 목록과 구현 상태 |
| `src/privacy_proxy/risk/quasi_identifiers.py` | 엔터티 분류와 지역 QI |
| `src/privacy_proxy/risk/resolver.py` | overlap 처리 |
| `src/privacy_proxy/risk/score.py` | 운영 위험평가 |
| `src/privacy_proxy/risk/stage.py` | async fail-closed 경계 |
| `src/privacy_proxy/risk/weighted_score.py` | 실험 가중식 |
| `src/privacy_proxy/l4_adapter.py` | PS/LC 및 전역 offset 변환 |

## 현재 정책

- 직접식별자: 최소 80점, `TOKENIZE`
- 서비스 식별자: 최소 85점, `TOKENIZE`
- 민감정보: `80 × confidence`, `TOKENIZE`
- 위치 QI만 있고 30점 이상: `GENERALIZE`
- 그 외: `ALLOW`

## 검증

- pytest 80개 통과
- Ruff 통과
- mypy strict 통과
- 지원 18종 모두 분류·가중치 존재
- `ETC`, 비표준 타입, span 불일치 fail-closed

## 다음 작업

1. 최신 develop 반영 및 `schemas.py` SSOT 유지
2. `pipeline.py`의 mock L5를 `run_l5_risk_scoring()`으로 교체
3. L3/L4 실제 fixture로 통합 검증
4. L5 실패 시 L6/L7 미호출 E2E 테스트
5. L5→L6 span별 정책 계약 확정
