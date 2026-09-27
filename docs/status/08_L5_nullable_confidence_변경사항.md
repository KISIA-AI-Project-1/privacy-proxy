> **2026-09-27 계약 변경:** 현재 스키마·L5 지원은 L3 13종 + L4 14종 = 27종입니다. 이전 이름 4개와 ETC는 제거했고 연령 QI를 지원합니다. 아래 내용은 변경 전 기록이며 [최신 계약](../status/09_L3_13종_스키마_반영.md)을 우선 참고하세요.

# L5 nullable confidence 및 tier 우선순위 반영

기준일: 2026-09-26. 사용자 확정 18종 및 tier 체계를 유지한 로컬 구현.

## 변경

- confidence: 필드 필수, 숫자 0~1 또는 null. 누락과 null은 다르며 null을 0으로 변환하지 않음.
- tier: 기본 MODEL 제거. 4종 중 하나를 반드시 전달. JSON 값은 소문자.
- source: 기존 unknown 기본값 유지. unknown/빈 출처는 confidence 비교에서 제외.
- resolver: tier → 보호 분류 → 길이. 이후 출처·타입의 고정 순서로 그룹을 정렬하고 같은 그룹의 숫자 confidence만 비교.
- 같은 출처·타입·tier 그룹에 null이 하나라도 있으면 그룹 전체의 confidence 비교 생략. 산정 방식이 다른 생산자는 서로 다른 source를 사용해야 함.
- 마지막 동률은 시작 좌표, normalized, 직렬화 값으로 결정하여 입력 순서 의존성을 제거.
- 패배한 탐지 구간이 동일 이상 보호 분류의 winner들로 전부 덮이지 않으면 ValueError. 부분 중첩을 임의 병합·잘라내지 않음.
- async stage는 해당 오류를 원문 없는 L5_VALIDATION_FAILED로 반환. 실패한 입력 탐지 목록 보존.
- 민감정보 null은 정책 대체 점수 80, 사유 기록, TOKENIZE. 직접/서비스/QI는 기존 점수 유지.
- 별도 실험 가중식은 confidence 미산정 시 ValueError. 확률을 임의로 생성하지 않으며 운영 함수에는 영향 없음.

## 검증

PYTHONPATH=src .venv/bin/pytest -q: 전체 100개 통과.
Ruff 및 strict mypy(14개 소스 파일) 통과.
Starlette/httpx deprecation warning 1건은 기존 의존성 경고.
추가 회귀 검증: null JSON 왕복, 필드 누락·범위 밖·NaN·null tier 거부,
직접/서비스/QI/민감정보 null 평가, 민감정보 0과 null 구분,
tier 우선순위, 입력 순서 독립, 다른 source confidence 비비교,
부분 중첩·포함 관계에서 구간 유실 및 보호 하향 차단, 실험 가중식 null 거부.

## 적용 한계 및 다음 작업

L3/L4 실제 출력 fixture와 develop 오케스트레이터는 이 브랜치에 없어 실연동은 미검증.
L6/L7 호출 차단은 오케스트레이터가 status=success를 검사해야 하므로 E2E 검증 필요.
부분 중첩 요청은 현재 실패 처리하며 span별 혼합 정책 계약 확정 후 처리 범위 확대 가능.
L4 base score/앵커 산정식은 producer 책임으로 그대로 두었으며 이번 변경에서 구현하지 않음.
커밋·push·배포 미실행.
