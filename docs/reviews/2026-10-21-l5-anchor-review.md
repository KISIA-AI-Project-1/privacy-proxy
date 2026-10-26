# L5 앵커 및 JSON 동률 검증

## 검증 대상

GitHub 재조회: develop dd9798f, feature/detection-ecommerce 9837cdf.
별도 로컬 codex/l5-anchor-priority의 미커밋 L5 초안을 함께 검사했다.
면허 제외 예외는 로컬 초안이며 원격 develop에 반영된 기능이 아니다.
이번 검증에서 운영 코드는 추가 수정하지 않았다.

## 통과

- 기존 앵커/L4/resolver/risk/L5/adapter 관련 185개 테스트 통과.
- 상품 항목 정책, E2E 결과 판정기, nullable 계약 관련 53개 테스트 통과.
- 상품 GENERALIZE → “상품”, 구매 패턴 ALLOW → 원문 유지 확인.
- 상품명·구매 패턴은 복원 매핑에 없고 전화번호는 매핑에 존재함을 확인.
- e2e_leak_test.py의 상품 일반화·조사 보정 기대값을 확인했다.

## 재현된 결함 (3개)

1. **직접 연결된 후보를 최종 승자로 보장하지 않는다.**
   `송장번호는 별도입니다. 주문번호: 112412345601`에 실제 L4는 ORDER_ID와 TRACKING_NUMBER를 모두 방출한다. 같은 구간의 면허 후보를 추가하면 L5 초안은 ORDER_ID의 직접 연결을 근거로 면허를 제거하지만, 남은 후보의 타입 문자열 비교에서 TRACKING_NUMBER가 승리한다. 예외의 근거와 최종 선택이 다르다. 로컬 초안의 결함이다.
2. **JSON 동률 비교가 앵커 근거를 버린다.**
   타입·생산자·구간·confidence가 같은 송장번호 후보 두 개 중 하나만 유효한 앵커를 가지면, 마지막 model_dump_json 비교에서 anchor_text=null인 후보가 선택된다. JSON의 null과 문자열 표현의 사전순 결과이며 근거 강도 판단이 아니다. 면허를 제거하는 데 사용한 앵커도 최종 결과에서 사라질 수 있다.
3. **비교 금지한 confidence가 JSON을 통해 다시 비교된다.**
   source=unknown인 같은 구간 후보에서 confidence 숫자만 서로 바꾸면 선택되는 앵커 근거가 달라진다. priority의 confidence_rank는 0으로 처리하지만 전체 JSON에 원래 confidence가 포함되어 이를 우회한다. JSON 전체 비교는 원격 코드에도 존재하는 문제다.

수정 전 별도 재현 테스트에서 3개 모두 실패했다. 해당 사례는 이후 `tests/unit/test_resolver_tie_breaks.py`의 정식 회귀 테스트로 옮겼으며 수정 후 통과한다.

수정 후 재현: `python -m pytest tests/unit/test_resolver_tie_breaks.py --tb=short`

## 검증 한계와 후속 수정 기준

전체 E2E 실행은 readiness 503으로 중단됐으며, 이번 환경에서 E2E 통과를 주장하지 않는다. E2E 판정기 단위 테스트 통과와 실제 모델을 사용하는 E2E 통과는 다르다.

면허 예외를 발생시킨 직접 연결 후보가 최종 선택에 반영되도록 하고, JSON 전체 비교 대신 앵커 근거와 비교 가능한 필드만 명시적으로 사용해야 한다. confidence를 비교하지 않는 완전 중복 후보의 선택/병합 정책도 입력 순서 독립성을 함께 검증해야 한다. 단순히 마지막 JSON을 삭제하면 입력 순서에 따른 결과가 발생할 수 있다.


## 후속 수정

위 내용은 수정 전 검증 기록이다. 이후 L5 수정에서 세 결함을 해결하고 `tests/unit/test_resolver_tie_breaks.py`로 재현 사례를 정식 회귀 테스트에 포함했다. 비교 불가능한 점수만 다른 완전 동률은 병합하지 않고 실패 처리한다. 최신 동작과 L4 확인 요청안은 `docs/status/11_L5_anchor_priority.md`를 따른다. 전체 E2E 및 L4 최종 계약 합의는 아직 완료되지 않았다.
