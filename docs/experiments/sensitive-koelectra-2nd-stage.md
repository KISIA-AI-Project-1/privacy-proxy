# sensitive/ 2단계 KoELECTRA 분류기 — 데이터 제작~학습 문제/해결/한계 정리

- **기간**: 2026-09-21 ~ 2026-09-27
- **모델**: `monologg/koelectra-small-v3-discriminator` + `AutoModelForSequenceClassification`(이진분류)
- **코드**: `l4/sensitive/predict.py`(추론 결합), `l4/sensitive/train.py`(학습),
  노트북 `l4/colab/koelectra_sensitive_train_colab.ipynb`
- **범위**: 1단계(`recognizers.py` 앵커 매칭)가 좁힌 후보를 2단계 모델이 "진짜
  민감정보 진술인가"로 재판정하는 구조. 이 문서는 2단계 학습 데이터 제작부터
  4종 배선 완료까지 과정에서 나온 문제·해결·한계만 다룸. 1단계 앵커 설계
  자체는 CLAUDE.md 참고.

---

## 1. 데이터 제작

FAMILY/HEALTH는 `nvidia/Nemotron-Personas-Korea`에서 원재료 추출 후 문체
변환, RELIGION/FINANCIAL은 원재료가 없어 LLM 직접 생성. 4종 각 600개(긍정
250 + negative_A 250 + negative_B 100)로 총 2,400개 제작 완료(2026-09-22).

### 문제 1 — negative_A 소스 편중으로 근접중복 위험

HEALTH negative_A "장애" 소스가 "결정 장애" 계열 관용구 하나에 쏠려서 뒤
배치로 갈수록 표현이 반복됨(배치 5·6에서 근접중복 4건 발생, 표현 변형으로
회피). **해결**: RELIGION/FINANCIAL 생성 시 origin(소재)마다 concept 6개를
처음부터 직접 작성해 분산시킴 — 근접중복 재시도 0회로 확인. HEALTH/FAMILY는
이미 만들어진 상태라 소급 반영 안 함(기록만).

### 문제 2 — validator의 부분 문자열 매칭 오탐

`must_include`/leak 체크가 부분 문자열 매칭이라 "아이템"⊃"아이", "강복용"⊃
"복용" 같은 오탐 발생. **해결**: validator 코드는 안 고치고 표현을 우회(짧은
문장 다듬다 앵커 리터럴이 활용형으로 사라진 사고 2건도 같은 방식으로 재수정).
근본 수정은 W7 이후 과제로 남김.

---

## 2. 학습 실행 — 데이터 결함 두 가지 발견 (2026-09-22)

1차 학습(레코드 단위 랜덤 분할 1,920/480)에서 accuracy 0.9833/f1 0.9804가
나왔는데, **사용자가 "너무 비정상적으로 좋다"고 의심 제기** — 액면가로
받아들이지 않고 원인 조사.

### 문제 1 — train/val 근접중복 누수

템플릿 기반 생성이라 "문구는 동일, concept 단어만 교체"된 형제 문장이
train/val에 나뉘어 들어감. char 3-gram Jaccard로 재보니 val 480건 중 72건이
train과 Jaccard > 0.5 — val이 사실상 "본 템플릿의 단어 교체판"이라 일반화
능력과 무관하게 점수가 부풀 수 있는 구조였음.

**해결**: `prepare_dataset.py`에 Union-Find 근접중복 클러스터링 추가, 클러스터를
원자 단위로 (category, label) 층화 8:2 분할. 재분할 후에도 accuracy가
0.9897로 **오히려 소폭 상승** — 누수가 점수 부풀리기의 주범이 아니었다는 뜻,
더 근본적인 원인이 따로 있다고 판단.

### 문제 2 — 어휘 지름길 학습(shortcut learning)

문맥 이해가 전혀 없는 BoW 나이브베이즈 베이스라인(stdlib `Counter`+`math.log`)을
같은 train/val에 돌려봄 — accuracy 0.9545. **단어 존재 여부만으로도 거의 다
맞힘.** concept 어휘가 label/category마다 사실상 배타적으로 고정돼 있어서,
KoELECTRA의 0.98~0.99가 "문맥을 이해해서"인지 "데이터가 원래 어휘로만
갈려서"인지 이 실험만으론 구분 불가 — 후자 쪽에 무게가 실림.

**교훈 정정**: 데이터 설계 시 "문장 시작 패턴이 라벨 간 공통이라 지름길
위험 낮음"이라 판단했었는데, 이건 틀렸음. 시작 패턴이 아니라 concept 어휘
전체가 라벨과 얽혀 있었던 것.

**해결 방향**: val 지표를 프로덕션 신뢰 지표로 쓰지 않기로 하고, concept
어휘 밖의 손수 작성 held-out 평가셋(`adversarial.jsonl`)을 별도로 만들어
실사용 성능을 따로 측정하기로 함.

---

## 3. adversarial.jsonl 실측 (2026-09-23)

62건(카테고리별 15 + 멀티앵커 2), concept 어휘 밖 표현 + 로컬 실측 FP 재사용
+ "대출" 하드케이스 + "복용" 경계 케이스로 구성. train/val과 근접중복 0.5
이하 확인(순수 held-out).

| 카테고리 | adversarial acc | BoW 대비 |
|---|---|---|
| 전체 | 0.7833 (val 0.9897 대비 -0.2063) | KoELECTRA 우위 (BoW 0.7000) |
| FAMILY | 0.93 | 우위 뚜렷 (BoW 0.60) |
| HEALTH | 0.93 | 우위 뚜렷 (BoW 0.80) |
| RELIGION | 0.67 | 동률 (BoW 0.67) |
| FINANCIAL | 0.60 | **열세** (BoW 0.73) |

KoELECTRA가 BoW보다 덜 떨어지긴 하지만(문맥 이해가 어느 정도 있다는 근거),
두 쪽 다 20%p 이상 떨어져서 val 0.9897은 확실히 지름길 학습에 부풀려진
수치로 확정. FAMILY/HEALTH는 실제 문맥 이해 근거가 있는 반면, FINANCIAL은
"도서관대출"·"매출 규모"·"이직"·"용돈"·"상여금" 등 재정난과 무관한 돈 관련
표현을 전부 positive로 오탐(정밀도 0.6154) — 금액/돈 관련 어휘 자체에
반응하는 지름길로 의심.

멀티앵커 윈도우 충돌도 이때 처음 실측 재현: 짧은 문장에 앵커 2개가 있으면
윈도우가 문자 그대로 동일해져 raw 확률도 완전히 같아짐(설계 한계, 아래
"6. 한계" 참고).

---

## 4. 지름길 원인 상세 진단 (2026-09-23~24, 진단만·코드 변경 없음)

### 4.1 "특정 어휘 과적합" 판정

FINANCIAL/RELIGION 오류 케이스의 raw 확률(softmax)을 직접 대조. FINANCIAL은
오탐 5건 중 4건이 고확신(이직 0.91·용돈 0.95·상여금 0.96·도서관대출 0.81),
RELIGION은 부정 방향 오탐(무교 0.96)과 미지 어휘 긍정 누락(세례 0.05)이
양방향으로 극단적 확신을 보임 — 둘 다 "학습 origin 표면형 밖으로 못 나간다"는
같은 근거의 양면. **negA 다양성 부족 가설은 반박됨**: RELIGION 8종·FINANCIAL
7종이 FAMILY 4종보다 많은데도 성능은 더 낮았음.

### 4.2 minimal pair 검증 — 통사적 신호(1인칭/3인칭) 가설 검증

FAMILY/HEALTH negA는 앵커가 항상 "관계명사+이/가"(3인칭 표지) 형태라
1인칭 자기서술과 통사적으로 갈리는 구조인데, FINANCIAL/RELIGION negA는 그런
구조 대조가 없었다는 게 가설. 기존 positive 문장을 1인칭→3인칭 전언으로
바꿔 직접 검증.

| 카테고리 | concept | 원본(1인칭) | 변형(3인칭 전언) | delta |
|---|---|---|---|---|
| FINANCIAL | 파산 | 0.9647 | 0.9345 | 0.0303 |
| FINANCIAL | 기초생활수급 | 0.9635 | 0.0733 | **0.8902** |
| FINANCIAL | 압류 | 0.9639 | 0.0298 | **0.9341** |
| FINANCIAL | 빚 | 0.9646 | 0.1274 | **0.8372** |
| RELIGION | 기독교 | 0.9638 | 0.9639 | -0.0001 |
| RELIGION | 제사 | 0.9641 | 0.9593 | 0.0048 |
| RELIGION | 불교 | 0.9642 | 0.9616 | 0.0026 |

- **RELIGION: 가설 기각.** 구조를 전혀 안 봄 — negA에 구조적 대조가 없었을
  뿐 아니라 모델이 구조 자체에 무감각. "다양성만 늘리는 재설계로는 부족할
  수 있다"는 결론으로 이어짐(→ 5.1에서 대조쌍 명시 도입).
- **FINANCIAL: 가설 부분 지지, concept마다 불균일.** 학습에 있던
  "실직_타인"의 "3인칭=부정" 신호가 다른 concept으로 일부 전이됐지만 완전한
  일반 규칙은 아님(파산은 무반응). **단, 이 결과가 adversarial의 FINANCIAL
  오탐(이직/용돈/상여금)을 설명하진 않음** — 그건 person-reference가 아니라
  valence/topic-relevance(고난 서술 대 단순 화제 언급) 축 문제라 별도.
  FINANCIAL은 최소 두 개의 서로 다른 지름길이 겹쳐 있을 가능성.

### 4.3 negation 프로브 9×3 전체 확대 (2026-09-26)

minimal pair(3개 concept)를 RELIGION/FINANCIAL 9개 concept 전체로 확대,
FAMILY/HEALTH도 처음으로 negation 프로브 실행.

- **RELIGION**: 부정문 8/9 FAIL, 무관문맥 4/9 FAIL — negA에 자기부정형
  반례가 아예 없었던 게 원인.
- **FINANCIAL**: negation 7/9 FAIL — 통과한 2개(실직·퇴사)는 negA에 "_타인"류가
  우연히 있었던 덕. valence 축(긍정적 financial 소식) negA는 전무 확인 —
  adversarial FP의 구조적 원인으로 재확인.
- **FAMILY/HEALTH: 6/6 FAIL — 긴급.** "저는 이혼 안 했어요"류 문장이
  확률 변화가 사실상 0(최대 하락폭 0.002)이었음. 이 둘은 이미
  `REFINED_CATEGORIES`에 있어 2단계가 라이브로 confidence를 emit
  중이라, 실사용에서 그대로 SENSITIVE_FAMILY로 emit될 리스크가 있었음.

---

## 5. 해결 — negA 재설계 + 재학습 (2026-09-26~27)

### 5.1 RELIGION/FINANCIAL negA 재설계

`RELIGION_NEGA` 13개 신규 origin(자기부정 9 + 무관문맥 4) +
`FINANCIAL_NEGA` 9개 신규 origin(자기부정 7 + valence 1 +
person-reference 1) 추가. FAMILY/HEALTH도 같은 사이클에 합류시켜
`이혼_부정`/`사별_부정`/`당뇨_부정`/`질환_부정` 등 자기부정 origin 추가
(합성 문장이라 Nemotron 추출이 아니라 LLM 직접 생성 방식 재사용).

### 5.2 재검증 결과

| 항목 | 이전 | 이후 |
|---|---|---|
| RELIGION 9×3(부정문/무관문맥) | 8/9, 4/9 FAIL | **9/9, 9/9 PASS** |
| FINANCIAL 9×negation | 7/9 FAIL | 9/9 PASS (단, 아래 신규 회귀 발생) |
| FAMILY/HEALTH negation(6종) | 6/6 FAIL | 5/6 완전 해결, "복용"만 부분 해결(0.9630→0.2640) |
| adversarial 전체 | 0.7833 | **0.8167** (RELIGION 0.67→0.80, FINANCIAL 0.60→0.7333) |

RELIGION/FINANCIAL negA 재설계가 held-out(adversarial) 성능도 실제로
끌어올림을 확인. 단 FAMILY/HEALTH는 각각 0.93→0.8667로 소폭 하락(negA
부정문 보강이 다른 adversarial 케이스 일부를 희생시킨 것으로 추정, 구체
원인 미조사).

### 5.3 신규 회귀 — FINANCIAL "기초생활수급" false negative

`기초생활수급_아님` negA를 추가하고 나니 정작 원본 positive 문장이
0.0269로 오분류됨. **원인**: negA 6개 템플릿 중 2개가 positive 템플릿과
접두어가 거의 겹침(예: "기초생활수급을 받고 있지 않은데" vs "받고 있어서").
negA 개수 자체는 원인이 아니었음 — 리터럴 출현 비율(neg/pos) 가설은 대조군
비교로 반박됨, 접두어 근접 충돌 유무가 실제 변별 요인으로 확인.

**해결**: `기초생활수급_아님` 6개 템플릿만 positive 템플릿 접두어를 전부
피해서 재작성(다른 8개 concept·다른 카테고리는 안 건드림). 재학습 후
positive 15/15·negA 15/15 전부 정상 확인(회귀 완전 해소).

부수 발견 — **`if __name__ == "__main__":` 가드 없는 스크립트의 import
부작용**: 헬퍼 함수만 가져오려던 import가 전체 재생성을 실행시켜 같은
random 스트림을 공유하는 무관한 131건까지 텍스트가 달라지는 사고 발생.
즉시 백업에서 복구 후 가드 추가로 근본 수정, remove+add 패턴으로 필요한
15건만 교체.

---

## 6. 최종 배선 — `REFINED_CATEGORIES` 4종 전체 편입 (2026-09-27)

2단계 재판정 대상 카테고리를 결정하는 `l4/sensitive/predict.py`의
`REFINED_CATEGORIES`를 단계적으로 확장:

1. **2026-09-23**: adversarial 실측 결과 FAMILY/HEALTH만 BoW 대비 유의미한
   이점이 있어 이 둘만 편입, RELIGION/FINANCIAL은 1단계 결과(confidence
   0.4 고정)를 그대로 emit.
2. **2026-09-27**: 위 negA 재설계 + 재학습으로 RELIGION/FINANCIAL의
   negation 축 문제와 기초생활수급 회귀까지 해소되어 4종 전체 편입.

`find_sensitive()`의 필터 로직(refined/passthrough 분리) 자체는 처음부터
카테고리 무관 범용 구조라 코드 변경 없이 `REFINED_CATEGORIES` 값만
갱신했음 — 특정 카테고리가 향후 다시 빠질 수 있으니 frozenset 필터 구조는
그대로 유지.

---

## 7. 한계 (해결 안 하고 기록만 한 것)

- **기초생활수급 OOD 프로브 잔여 실패.** 실제 학습 분포 내 텍스트(positive
  15·negA 15)는 전부 정상이지만, 손수 작성한 프로브 문장 1건("혹시
  기초생활수급을 신청해서 받는 중인데...")은 여전히 0.0271로 실패. negA
  재충돌은 아님(추가 진단으로 표면형 충돌 가설 기각) — positive 표본
  부족(15건)·문형 편중으로 인한 일반화 한계로 추정. 데이터 수정으로 고칠
  문제가 아니라는 뜻은 아니고, positive 확충 시 개선 가능성 있음. W7 실측
  1순위 확인 대상.
- **"복용" 부정문 마진 얕음.** 0.9630→0.2640으로 threshold(0.7) 기준 PASS는
  하지만 다른 5개 negation(0.02대)보다 마진이 훨씬 얕음. 동사형 앵커라
  부정 표현과 완전히 분리가 안 되는 구조적 약점으로 추정. "복용" 앵커 자체의
  처리 방침(제거/공동출현 조건/유지)은 이 문서 범위 밖 — 별도 결정 대기.
- **멀티앵커 윈도우 충돌 — 4종 전체 라이브 전환으로 영향 범위 확장.**
  `build_windows`가 후보별 독립으로 윈도우를 자르는데, 짧은 문장에 앵커
  2개가 있으면 윈도우가 문자 그대로 같아져 raw 확률도 동일해짐 — "이
  문장이 민감한가"는 판단해도 "어느 앵커가 민감한가"는 구분 불가. 이전엔
  FAMILY×HEALTH 조합에서만 실제 confidence에 영향을 줬지만(RELIGION/
  FINANCIAL은 1단계 고정값이라 무관했음), 이제 4종 전부 2단계를 타므로 4종
  간 모든 조합에서 발생 가능. 윈도우를 좁히면 문맥 손실 트레이드오프가
  생겨 코드 수정 안 함 — W7 실측 대상.
- **FAMILY/HEALTH adversarial 소폭 하락(0.93→0.8667) 원인 미조사.** negA
  부정문 보강이 다른 adversarial 케이스를 일부 희생시킨 것으로 추정되나
  구체 오류 케이스는 확인 안 함.
- **FINANCIAL 오탐의 valence/topic-relevance 축은 미해결.** minimal pair가
  검증한 건 person-reference(1인칭/3인칭) 축뿐 — "상여금·용돈"류 긍정적
  financial 화제에 대한 반응은 별도 축 문제로 분리되었고 이번 재설계
  범위에는 포함 안 됨.
- **anchors.py 커버리지 갭.** HEALTH "갑상선"/"인슐린", FINANCIAL "신용점수"/
  "연체"/"연소득" 미탐 확인 — 후보만 정리, 미반영. "연체"는 "대출"과 같은
  계열의 비금융 맥락 충돌 위험(도서관대출류), "연소득"은 L4/L5 역할 분담
  재확인 필요.
- **"무교" 라벨 정의 애매성.** "무교"(비종교) 자기 진술이 SENSITIVE_RELIGION
  대상인지 카테고리 정의 자체가 불확실 — 학습 데이터에 대칭되는 positive
  origin이 없음. 코드/데이터 문제가 아니라 정의 문제라 형지원 확인 필요.
- **val 지표는 여전히 스모크 테스트 신호일 뿐.** 지름길 학습 가능성이
  이번에 상당 부분 해소됐지만, val accuracy(0.96~0.99대)를 프로덕션 신뢰
  지표로 다시 쓰기 시작해도 되는지는 별도 판단 필요 — adversarial.jsonl
  기준으로만 실사용 성능을 봐야 함.
- **threshold 0.7·window_chars 60은 여전히 임의 초기값.** W7 합성 평가셋
  실측 후 조정 대상(코드에 TODO 유지).

---

## 8. 산출물

| 파일 | 상태 |
|---|---|
| `l4/sensitive/predict.py` | 커밋 대상 — 2단계 결합 로직, `REFINED_CATEGORIES` |
| `l4/sensitive/train.py` | 커밋 대상 |
| `tests/unit/l4/test_sensitive_predict.py`, `test_sensitive_train.py` | 커밋 대상 |
| `l4/colab/koelectra_sensitive_train_colab.ipynb` | 커밋 대상 |
| `l4/sensitive/data/*.json`, `train.jsonl`/`val.jsonl`/`adversarial.jsonl` | gitignore, 로컬 전용 |
| `l4/sensitive/data/tools/*.py`(생성·검증·진단 스크립트) | gitignore, 로컬 전용 |
| 모델 가중치(`outputs/koelectra-small-sensitive-v1/model/`) | 레포 미포함, Google Drive 보관 |

### 재현 명령어

```bash
uv sync --extra training
uv run python -m l4.sensitive.train --run-name koelectra-small-sensitive-v1
```

학습 데이터(`l4/sensitive/data/`)는 전부 gitignore라 로컬 생성 스크립트로
재생성하거나 별도 경로로 옮겨와야 함.
