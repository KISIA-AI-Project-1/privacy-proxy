# L5 여권·번호 충돌 예외

## 변경

`src/privacy_proxy/risk/resolver.py`에 여권 전용 예외를 추가했다.
동일 segment/start/end에 명확한 번호 라벨이 직접 연결된 L4 RULE_ANCHORED
후보 타입이 하나일 때만 RULE_ANCHORED 여권 후보를 제외한다.
허용 라벨은 resolver의 `_PASSPORT_OVERRIDE_ANCHORS`에 명시한다.
기존 면허 예외, 전체 priority 순서, 보호 구간 검증은 유지한다.

## 범위와 제한

- 고객번호·회원번호·주문번호·구매번호·송장/배송번호 계열의 명확한 라벨만 사용한다.
- 배송·등록번호·우리·입금 같은 넓은 라벨과 계좌번호는 여권 예외에 포함하지 않는다.
- 원문과 좌표가 불일치하거나 직접 연결이 아니면 예외를 적용하지 않는다.
- 복수의 명확한 L4 번호 타입이 직접 연결되면 기존 우선순위를 유지한다.
- 이 변경은 여권 후보만 제외한다. 다른 번호 후보끼리의 의미 충돌은 해결하지 않는다.
- 여권 라벨과 번호 라벨이 같은 값에 함께 붙는 문장을 의미적으로 판별하지 않는다.
  L3 여권의 명시적 앵커 전달 및 복수 라벨 정책은 별도 검토 대상이다.
- develop `b9b8350`을 기준으로 적용했다. 전체 L3/L4/L5 실행 및 실제 외부
  API 호출을 검증했다고 주장하지 않는다.

## 회귀 테스트

`tests/unit/test_passport_anchor_priority.py`에 허용 라벨, 입력 순서 변경,
간접/원거리/잘못된 앵커, 다른 범위/segment, deterministic 후보 유지,
복수 번호 타입 충돌 및 실제 L5 stage의 분류·토큰화 정책을 검사하는 테스트를 추가했다.

## 로컬 검증 결과

- resolver/앵커/위험 점수/L5 stage 관련 pytest 최종 실행: 146 passed, 7 deselected.
- 제외한 7건은 실제 L4 인식기를 로드하는 통합 테스트다. 프로젝트 가상환경의
  탐지 의존성(`phonenumbers`, `presidio-analyzer`) 부족을 확인한 뒤 제외했다.
- 새 테스트의 L5 stage 확인은 `asyncio.run()`으로 pytest 안에서 실행했다.
- ruff check, ruff format --check, git diff --check 통과.
- 최종 실행은 프로젝트 Python 3.11 가상환경에서 pytest-asyncio 플러그인을
  명시적으로 로드했다. 초기 패키지 파일 읽기 지연 후 선택한 스위트는 완료했다.
