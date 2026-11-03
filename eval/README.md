# 최종 성능 평가

프록시 전체(L2~L8)를 대상으로 가명처리 후에도 LLM 답변의 유용성이 유지되는지, PII가 밖으로 새지 않는지 측정함.
멘토 피드백(딕셔너리 왕복 정확도, Task metric, Critical Fact Preservation, LLM-as-a-Judge, BERTScore, 누수·재식별)을 우리 구조에 맞게 줄였음.

- 평가 대상: L2 파싱 → L3·L4 탐지 → L5 위험도·겹침 정리 → L6 vault 토큰화/일반화 → L7 LLM → L8 역매핑
- **L4 NER은 항상 켬**(프록시 구성 요소임). `run.py`가 강제로 켜고, 꺼져 있으면 중단함
- 모든 결과에 코드 커밋 해시를 같이 기록함(`run.py`가 결과 파일에 `commit`을 남김)

## 진행 현황 (2026-11-03 기준, 코드 `dc4119c`)

| 지표 | 스크립트 | 상태 | 현재 수치(헤드라인 후보 `llm_claude` / `llm_gemini`) |
|---|---|---|---|
| ① 딕셔너리 왕복 | `run.py`(echo) + `score.py` | **측정 완료(960건)** | 가역 처리만 있는 레코드 432/432 / 330/330 |
| ② 보호율 / precision | `run.py`(echo) + `score.py` | **측정 완료(960건)** | 보호율 0.741 boot[0.669, 0.807] / 0.713 boot[0.601, 0.827], precision 0.982 / 0.968 |
| ③ Task metric | `run.py --l7 real` + `score.py` | **측정 완료(Sonnet 5.5, 288건)**. lenient는 사람 라벨 검증 대기 | lenient 원본 0.980 / 가명 0.980, loss 상한 +5.9%p / 0.958 / 0.958, 불일치 0쌍 (5-3) |
| ④ CFP | `score.py` | **측정 완료** | 원본 0.946 / 가명 0.956 / 0.951 / 0.959 (5-3) |
| ⑤ BERTScore | `bertscore.py` | **측정 완료**(원본 재실행 기준선 포함, 보조) | 가명 0.802 vs 기준선 0.847 / 0.797 vs 0.842 (5-3) |
| ⑥ LLM Judge | `judge.py` | **측정 완료**(`gemini-3.5-flash-lite`, 30건). 위치 바꾸면 판정이 갈리는 비율이 높아 **한계로 기재** | 의미 다름 4/30, 그중 실제 프록시 원인 2건 (5-3) |
| 원본 재실행 기준선 | `baseline.py` | **측정 완료** | L7 자체 변동: lenient 판정 갈림 1/102쌍, BERTScore 0.847 (5-3) |
| masked_star 비교 | `masked.py` + `score.py --masked` | **측정 완료** | Task 0.980 → **0.755**(loss +22.5%p), 값형 사실 0.991 → **0.310** (5-3) |
| 재식별 | - | 범위 제외(한계로 기재) | - |

| 데이터 그룹 | 시나리오 | 레코드 | 상태 |
|---|---|---|---|
| `template_claude` | 15 | 150 | 완료. 규칙 아는 작성자라 헤드라인 제외 |
| `llm_claude` | 48 | 480 | 완료(시나리오 12종 × 4) |
| `llm_gemini` | 33 | 330 | 완료(시나리오 11종 × 3) |
| `hand_*` | - | - | 미착수. 작성자 미정 |

남은 것: **lenient 검증용 사람 라벨 57건**(팀원에게 맡김, `~/eval-data/label_sheet.tsv`), 손작성 그룹 작성자, 보고서.

## 1. 데이터셋

한 건 = 한 레코드(jsonl).

```
id, group, persona_uuid, prompt,
gold_pii[{start, end, type, value}],
task{type: 분류|추출|QA|자유서술, reference},
critical_facts[{fact, kind: invariant|equivariant}]
```

만드는 방식은 3층 조립임.

1. **사람 정보**: [Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea)(CC BY 4.0)에서 이름·나이·성별·시군구를 가져옴. 이름은 서술문의 `○○○ 씨`에서 뽑음(2,000건 중 100% 추출됨).
2. **가상 PII**: `build_dataset.py`가 생성해서 템플릿 자리에 직접 넣음. 그래서 gold 좌표가 정확함.
   - 주민·외국인·사업자번호는 체크섬을 맞춤(L3가 검증하므로)
   - 전화 `010-0000-xxxx`, 이메일 `@example.com`, 지번 동/리는 `l4/recognizers/legal_dong.txt`, 도로명은 페르소나 시군구 + 가상 도로명
3. **이커머스 CS 문맥**: `templates.yaml`의 시나리오(환불 판단, 배송 문의, 답장 초안, 요약, 금액 QA 등). `{SLOT}`은 가상값으로 채우고, `[[원문|TYPE]]`은 그대로 두되 gold로 표시함(건강·상품처럼 생성기가 없는 값).

원칙:
- 실제 개인정보는 쓰지 않음
- **작성자가 탐지 규칙을 모르게 함.** 규칙을 아는 사람이 쓰면 탐지에 유리한 문장(앵커가 값 바로 앞에 붙음, 질병어가 상품명 앞에 옴 등)이 섞여 점수가 부풀음. 손작성 그룹은 [WRITING_GUIDE.md](WRITING_GUIDE.md)(시나리오·PII 종류·형식만 있음)만 보고 씀. 자기 레이어의 규칙을 아는 팀원은 그 레이어 PII가 주인 문장은 쓰지 않는 게 좋음. LLM 생성 그룹도 같은 가이드만 프롬프트로 줌
- 그룹 이름: `template_claude`(규칙을 아는 Claude가 씀, **헤드라인 수치에서 제외**) / `hand_<이니셜>`(규칙 모르는 팀원) / `llm_<모델>`(가이드만 준 LLM 생성)
- **group별로 점수를 따로 냄.** 생성기 어휘 밖 데이터에서 점수가 크게 떨어진 전례가 있음(합성 val 0.95 → 어휘 밖 0.78). 손작성·LLM 생성·템플릿을 섞고 합친 평균은 헤드라인으로 쓰지 않음
- 데이터·결과 파일은 레포 밖에 둠(`~/eval-data/`)

### invariance / equivariance

가명처리 종류에 따라 답변이 지켜야 할 성질이 다름. 레코드의 `critical_facts.kind`로 구분함.

| 처리 | 대상 예 | 성질 | 판정 |
|---|---|---|---|
| 토큰화(가역) | 이름, 주문번호, 전화 | **equivariant**: 입력 값이 바뀌면 답변의 값도 같이 바뀌고, 역매핑 뒤 원본 값으로 정확히 돌아와야 함 | 복원 답변에 원본 값이 그대로 있는지 |
| 일반화(비가역) | 상품→"상품", 연령대 | **invariant**: 값은 못 돌리므로 판단·결론이 바뀌면 안 됨 | 원본 경로와 가명 경로의 판단이 같은지 |

## 2. 지표와 측정 방법

| # | 지표 | LLM 호출 | 정의 |
|---|---|---|---|
| ① | 딕셔너리 왕복 정확도 | 없음 | L7 대신 가명 프롬프트를 그대로 응답으로 흘림(echo, 7자 청크). 복원문 == 원문 비율. 비가역 처리가 있는 레코드는 따로 셈(원리상 불일치) |
| ② | PII 보호율 / 누수 | 없음 | gold 값의 글자 전체가 토큰화·일반화되고 L7 payload 어디에도 그 값이 없으면 보호됨. 보호율 = 보호된 gold / 전체 gold. 실패는 missed(미탐)·kept(탐지됐으나 정책상 원문 유지)·partial(일부만 가림)으로 나눔. **precision = gold와 겹치는 마스킹 스팬 / 전체 마스킹 스팬**(과탐 측정, ③ utility loss 원인 설명용). 전제: gold가 빠짐없이 표시돼 있어야 함 |
| ③ | Task metric | 있음 | 같은 과제를 원본 프롬프트 / 가명 프롬프트+역매핑 두 경로로 보냄. 두 경로 모두 같은 L7 함수(시스템 프롬프트 포함)를 거쳐 조건 차이는 가명처리뿐. 채점(공백·문장부호 무시): 분류 = 답이 정답으로 시작, QA = 숫자 정답은 포함·아니면 시작, 추출 = 정답 값 전부 포함(레코드 단위 정확도). **utility loss = 원본 정확도 − 가명 정확도**가 핵심. 같은 레코드의 두 경로 비교라 paired bootstrap CI + McNemar로 검정 |
| ④ | Critical Fact Preservation | 없음(③ 응답 재사용) | 보존된 핵심 사실 / 전체 핵심 사실. 원본 답변과 복원 답변 각각에서 세고 차이를 paired로 비교. 사실이 답변에 문자열로 있는지(공백·문장부호 무시) 검사, 분류 정답과 같은 사실은 ③ 규칙으로 판정. equivariant / invariant × 값형(숫자·gold 값) / 서술형으로 나눠 집계. 서술형(예: `진료비 보상 불가`)은 문자열 검사라 과소 측정됨 → ⑥ Judge로 보완 |
| ⑤ | BERTScore | 없음(로컬 모델) | 원본 답변 vs 복원 답변, 한국어 모델(`klue/roberta-large`, 채점용 임베딩이며 L4 NER(`klue/bert-base` 파인튜닝)과 무관). `bert_score` 패키지 없이 직접 계산: 레이어 17 토큰 임베딩 greedy cosine 매칭 F1, idf·baseline rescale 없음(점수 절대값은 패키지 수치와 다름, 그룹 간 비교용). 보조 지표로 표에만 넣음. 숫자·부정 하나가 바뀌어도 점수가 높을 수 있어서 단독 사용 안 함 |
| ⑥ | LLM-as-a-Judge | 있음 | 자유서술 과제만, 기본 30건. 동치 / 경미한 차이 / 의미 다름 3단계. A/B 위치 바꿔 2회 판정, 둘이 같을 때만 그 라벨·다르면 `불일치`. 판정 모델은 L7 답변 모델과 다르게. 사람 라벨과 일치율(κ)은 시간 남으면 |
| - | 재식별 공격 | - | 이번 범위에서 제외. 가명 프롬프트에 남는 준식별자(나이·지역·직업 등)를 정성적으로 정리하고 한계로 기재 |

CFP는 단일 표준 지표가 아니라 요약·사실일관성 쪽 key-fact recall 계열 개념이라 위 정의를 우리가 명시해서 씀.
단일 비율은 cluster bootstrap 95% CI(클러스터=템플릿)를 주로 쓰고 Wilson은 참고로 병기함. 같은 템플릿에서 나온 레코드끼리는 독립이 아니라서 Wilson만 쓰면 구간이 실제보다 좁게 나옴.
경로 간 차이(③)는 paired bootstrap과 McNemar로 계산함.
템플릿 수가 적으면 bootstrap 구간도 불안정하므로(클러스터 1~2개면 의미 없음) 템플릿 수를 결과와 같이 적음.

## 3. 일정 (2026-11-02 ~ 11-07)

| 날짜 | 할 일 | 상태 |
|---|---|---|
| 11-02 | 스키마 확정, 생성기·하네스 작성, ①② 실행(시나리오 31개 × 페르소나 10명 = 310건). ③④⑤⑥ 스크립트 작성·키 없이 검증 | **완료** |
| 11-03 | 데이터 확장(시나리오 31 → 96개, 960건). `llm_claude` 32개·`llm_gemini` 33개 추가, 검수, ①② 재실행. 손작성은 작성자 미정 | **완료**(손작성 제외) |
| 11-04 | 실제 L7로 원본·가명 두 경로 호출(레코드 수 × 2회), ③ | **11-03 완료**. Gemini는 할당량 소진으로 폐기(5-2), Sonnet 5.5로 288건 |
| 11-05 | ④ CFP, ⑤ BERTScore, masked_star | **11-03 완료** |
| 11-06 | ⑥ Judge 30건, 이상치 원인 분석, lenient 사람 라벨 일치율 | Judge **11-03 완료**. 라벨 대기 |
| 11-07 | 보고서 작성, 버퍼 | 대기 |

## 4. 실행 방법

```bash
# 1) 페르소나 샤드 1개 받기(220MB, 레포 밖)
mkdir -p ~/eval-data/nemotron
curl -L -o ~/eval-data/nemotron/train-00000.parquet \
  https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea/resolve/main/data/train-00000-of-00009.parquet

# 2) 데이터셋 생성(템플릿당 N건, seed 고정)
uv run python eval/build_dataset.py --personas ~/eval-data/nemotron/train-00000.parquet \
  --per-template 10 --out ~/eval-data/data.jsonl

# 3) 파이프라인 실행(기본 --l7 echo, NER 항상 켬)
PYTHONPATH=src:. uv run --extra detection python eval/run.py \
  --data ~/eval-data/data.jsonl --out ~/eval-data/run_echo.jsonl

# 4) 채점(①②)
uv run python eval/score.py --data ~/eval-data/data.jsonl --run ~/eval-data/run_echo.jsonl

# 5) 실제 LLM 두 경로(③④). .env에 CLAUDE_API_KEY 등. 중간에 끊겨도 같은 명령으로 이어서 돌림
set -a; . ./.env; set +a
PYTHONPATH=src:. uv run --extra detection python eval/run.py \
  --data ~/eval-data/data.jsonl --out ~/eval-data/run_real.jsonl --l7 real --model <L7 모델>
uv run python eval/score.py --data ~/eval-data/data.jsonl --run ~/eval-data/run_real.jsonl   # ①은 echo에서만, ②③④

# 6) BERTScore(⑤). 첫 실행 때 klue/roberta-large(1.3GB) 받음
PYTHONPATH=src:. uv run --extra detection python eval/bertscore.py \
  --data ~/eval-data/data.jsonl --run ~/eval-data/run_real.jsonl

# 6-1) masked_star 비교 경로(같은 스팬을 ***로 지운 프롬프트를 같은 L7에 보냄)
PYTHONPATH=src:. uv run --extra detection python eval/masked.py \
  --data ~/eval-data/data.jsonl --run ~/eval-data/run_real.jsonl --out ~/eval-data/masked.jsonl --model <L7 모델>
uv run python eval/score.py --data ~/eval-data/data.jsonl --run ~/eval-data/run_real.jsonl --masked ~/eval-data/masked.jsonl

# 7) Judge(⑥). L7과 다른 모델로
PYTHONPATH=src:. uv run --extra detection python eval/judge.py \
  --data ~/eval-data/data.jsonl --run ~/eval-data/run_real.jsonl --model <판정 모델> --out ~/eval-data/judge.jsonl
```

- `--model`은 `claude-*`면 Claude 경로, `gemini-*`면 Gemini 경로, 그 밖은 OpenAI 경로로 감(L2 어댑터 규칙). L1 허용 모델 검사는 `run.py`가 지정 모델만 허용하는 평가용 사용자로 통과시킴
- `temperature 0`, `max_tokens 1024`로 보냄
- 분당 호출 제한이 있으면 `run.py`·`masked.py`에 `--sleep <초>`(레코드 사이 대기). Gemini 무료 등급은 `--sleep 8`에서 429가 거의 없었음

NER 가중치는 `outputs/klue-ner-base-e3/model/`에 있어야 함(깃에 없음). 경로는 `L4_NER_MODEL_PATH`로 바꿀 수 있음.

| 파일 | 역할 |
|---|---|
| `build_dataset.py` | 페르소나 + 가상 PII + 템플릿 → 레코드(gold 좌표 포함) |
| `templates.yaml` | 이커머스 CS 시나리오(`template_claude`). 손작성은 같은 형식으로 별도 파일 |
| `WRITING_GUIDE.md` | 손작성 팀원에게 주는 가이드. 탐지 방식은 일부러 뺐음 |
| `run.py` | 실제 파이프라인 실행(echo / real). payload·가명문·복원 답변·원본 경로 답변·탐지·처리 결과 저장 |
| `score.py` | ①②③④ 채점. 보호율·precision, Task 정확도(strict·lenient)·utility loss(paired bootstrap·McNemar), CFP. `--masked`로 masked_star 비교. group별·타입별 표 |
| `choices.yaml` | lenient 채점용 템플릿별 선택지(프롬프트의 보기를 그대로 옮김) |
| `masked.py` | masked_star 비교 경로 실행 |
| `bertscore.py` | ⑤ 원본 답변 vs 복원 답변 BERTScore F1, 클러스터 bootstrap |
| `judge.py` | ⑥ 자유서술 답변 동치 판정, 위치 바꿔 2회 |
| `baseline.py` | 원본 경로 재실행 기준선(L7 자체 변동) |
| `cost.py` | Claude 토큰 비용 원장·상한(`--budget`) |
| `label_agree.py` | 사람 라벨과 lenient 일치율 |

## 5. 현재 결과 (960건)

조건: 커밋 `dc4119c`, L7 echo, NER 켬, 시나리오 96개 × 페르소나 10명. 데이터 `~/eval-data/data_v2.jsonl`, 결과 `run_echo_v2.jsonl`.
추가 데이터: `llm_claude_v2.yaml`(남은 시나리오 8종 × 4, 새 Claude 세션), `llm_gemini.yaml`(11종 × 3, Gemini). 둘 다 WRITING_GUIDE만 줌(요청문 `llm_request_*.md`).
생성 순서를 기존 파일 뒤로 붙여서 앞 310건은 1차와 바이트 단위로 같음(seed 공유 스트림).
검수 수정은 Gemini 파일만 2건(원본 `llm_gemini.v1-raw.yaml`): `{AMOUNT}원`→`{AMOUNT}`(생성기가 "원"을 붙임, 5곳), `llmg_auth_02`에서 `{AGE}` 줄 삭제(페르소나 나이가 성인이라 `10대 청소년` 설정과 정답이 모순). gold 범위·정답은 안 건드림.

| 그룹 | 시나리오 | ① 왕복(가역만) | ② 보호율 | bootstrap 95% (클러스터) | Wilson(참고) | ② precision | 이름(PERSON_KO) |
|---|---|---|---|---|---|---|---|
| template_claude (규칙 앎) | 15 | 140/140 | 407/450 = 0.904 | [0.810, 0.987] | [0.874, 0.928] | 404/404 | 127/140 |
| llm_claude (규칙 모름) | 48 | 432/432 | 1082/1460 = **0.741** | [0.669, 0.807] | [0.718, 0.763] | 1108/1128 = 0.982 | 252/292 = 0.863 |
| llm_gemini (규칙 모름) | 33 | 330/330 | 585/820 = **0.713** | [0.601, 0.827] | [0.682, 0.743] | 600/620 = 0.968 | 220/230 = 0.957 |

- 차단은 그대로 8/960(`llmc_reply_03`만). 새 시나리오에서 추가 차단 없음
- llm_claude 구간 폭이 0.224 → 0.138로 좁아짐(클러스터 16 → 48). 시나리오 수가 구간을 정한다는 1차 관찰과 일치
- 1차(0.780)보다 낮아진 건 새 시나리오에 앵커 없는 번호·민감 상품·나이가 더 많아서임. 타입 구성이 달라 1차 수치와 직접 비교하면 안 됨

**타입별(규칙 모름 두 그룹 합산, 실패만)**. 대부분 소수 시나리오에서 나온 것이라 원인 사례로 씀.

| 원인 | 타입 | 보호 | 예 |
|---|---|---|---|
| 앵커 없음 | ORDER_ID | 310/430 | `안주연님 20260304615881 단순변심`, `건(20260916-…)`, `[20260310-…] 요청하신`, `질문: 위 규정에 따라 2026…` |
| 앵커 없음·앵커가 뒤 | CUSTOMER_ID | 60/110 | `회원 89290327`(`회원` 단독), `cs139580 회원 반품완료건`, `고객: 조은옥 (81987116)` |
| 탐지기 없음/앵커 없음 | AGE / AGE_GROUP | 0/40 / 0/32 | `37세 여성고객`, `(56세)`, `20대 후반 고객`, `(10대 청소년)` |
| 사전 밖 | PRODUCT_ITEM | 40/170 | `멜라토닌 10mg 120정`, `텐가 에그 6종 세트`, `성인용 기저귀 대형`, `요실금 팬티`, `여성 유산균` / partial: `얼리체크 임신테스트기 5개입` |
| 프레임 밖 | SENSITIVE_HEALTH | 40/110 | `치매가 있으셔서`, `갱년기 때문에`, `임산부라`, `남성 질환 때문에`, `임신 축하 선물` |
| 미탐 | SENSITIVE_SEX_LIFE / PURCHASE_PATTERN | 0/10 / 0/40 | `남자친구랑 같이 쓰려고`, `매달 1일 정기구매`, `6개월째 복용` / kept: `3년째 매달 정기배송` |
| 정책(KEEP) | LOCATION | 0/60 | `분당`, `판교`, `우도`, `강남구` |
| NER 경계·미탐 | PERSON_KO / PERSON_EN | 472/522 / 30/40 | 표·목록 칸(`성명 유종인`, `\| 임금화 \|`), 1~2글자 이름(`서신`, `이영`), 붙여쓰기 `고객김제인` / `JIHYE PARK으로` partial |
| 반복 값 누락 | ORDER_ID | (위에 포함) | `llmg_refund_02`: 같은 주문번호가 `주문번호:` 뒤(탐지)와 `질문: 위 규정에 따라 …`(미탐)에 두 번 나옴 → 첫 번째는 토큰화됐지만 두 번째가 원문으로 나감(`leak_elsewhere`). **탐지된 값의 다른 등장 위치를 같이 가리는 처리가 없음** |

**gold 밖 마스킹(과탐) 40건, 전부 L4 주소**:
- `ADDRESS_ROAD` 30건: `배송지연으로 3`, `계좌로 2`, `입금으로 1~10`. `~로` + 숫자를 도로명+건물번호로 잡음. 정보 손실만 있고 누수는 아님(숫자 `3일`·`2~3일`이 토큰으로 바뀌어 ③ 답변에 영향 줄 수 있음)
- `ADDRESS_DETAIL` 10건: `1층`(공동현관 위치 설명)

## 5-1. 1차 결과 (310건, 참고)

조건: 커밋 `dc4119c`(develop, main `0d8641f`와 코드 동일), L7 echo, NER 켬, 시나리오 31개 × 페르소나 10명(`--per-template 10`, 고유 페르소나 306·고유 이름 277).
데이터: `templates.yaml` 15개(`template_claude`) + 다른 Claude 세션이 WRITING_GUIDE만 보고 쓴 16개(`llm_claude`, 레포 밖 `~/eval-data/llm_claude.yaml`).
`llm_claude`는 레포를 열지 않은 새 세션(CLAUDE.md·탐지 코드 미노출)에 WRITING_GUIDE 내용을 프롬프트로 주고 받음. 시나리오 4종(환불·반품, 배송 지연, 민감 상품, 고객 답장)을 4개씩. Claude 계열이라 `template_claude`와 어휘가 겹칠 수 있음 → 다른 모델(Gemini 등)이나 사람이 쓴 그룹을 같이 보고하는 게 좋음.

| 그룹 | ① 왕복(가역만) | ② 보호율 | bootstrap 95% (클러스터) | Wilson(참고) | ② precision | 이름(PERSON_KO) 보호율 |
|---|---|---|---|---|---|---|
| template_claude (규칙 앎) | 140/140 | 407/450 = 0.904 | [0.810, 0.987] (15) | [0.874, 0.928] | 404/404 | 127/140 = 0.907 boot[0.836, 0.964] |
| llm_claude (규칙 모름) | 132/132 | 398/510 = **0.780** | [0.663, 0.887] (16) | [0.742, 0.814] | 395/395 | 112/132 = **0.848** boot[0.734, 0.936] |

**페르소나를 늘려도 구간이 거의 안 좁아짐.** 페르소나 2명(62건) → 10명(310건)에서 llm_claude 보호율은 0.782 → 0.780, bootstrap 폭은 [0.650, 0.902] → [0.663, 0.887]. Wilson만 좁아짐(레코드를 독립으로 보는 착시). 같은 시나리오 안에서는 이름 외 값이 바뀌어도 탐지 결과가 같기 때문. **구간을 좁히려면 시나리오 수를 늘려야 함**(±0.05 목표면 약 100개). 페르소나 확대는 이름(NER) 표본에만 의미 있음.

**파이프라인 차단 8건(8/310 = 2.6%)**: 전부 `llmc_reply_03`(10건 중 8건), `L5_VALIDATION_FAILED`. NER이 `은파리 710-10 114동 802`(호 앞에서 끊김)를 LOCATION_INFORMAL로, L4가 `은파리 710-10`(ADDRESS_LOT)·`114동 802호`(ADDRESS_DETAIL)를 따로 잡음. L5는 버리는 span이 승자 span들로 완전히 덮여야 하는데 두 주소 span 사이 공백이 안 덮여 fail-closed로 막음. 누수는 없지만 요청이 실패함(가용성 문제). 알려진 LOCATION_INFORMAL↔주소 겹침 병합 정책 미결 건과 같은 원인. 차단된 레코드는 ①② 집계에서 빠짐.

- 규칙을 모르는 작성자 쪽이 보호율이 낮음. 작성자 편향 지적이 수치로 확인됨 → `template_claude`는 헤드라인에서 뺌
- 비가역(일반화) 포함 레코드 왕복은 두 그룹 모두 0(설계상 복원 불가, `콘돔`·성인용품→"상품")
- precision 1.000은 과탐이 없었다는 뜻일 뿐. 문장이 짧고 gold 밖 고유명사가 적어서 과탐 기회가 적음

**llm_claude 실패 유형 (페르소나 2명·62건 때 분류한 사례. 310건 타입별 건수는 `score.py` 출력 참고)**

| 원인 | 타입 | 건수 | 예 |
|---|---|---|---|
| 앵커 없음 | ORDER_ID | 2 | `○○○님 20260304098199 단순변심` |
| NER 경계·미탐 | PERSON_KO | 4 | `고객주우영`(붙여쓰기) 미탐, `배주형`→`배주`, `오혜림`→`림` |
| 앵커 없음 | AGE | 4 | `50세 여성고객` |
| 미탐 | AGE_GROUP | 2 | `○○○님 60대 어머님` |
| 사전 밖·수식어 없음 | PRODUCT_ITEM | 4 | `치질연고`, `생리컵` |
| 미탐 | SENSITIVE_HEALTH | 2 | `다음주 수술 잡혀서` |
| 미탐 | SENSITIVE_SEX_LIFE | 2 | `남자친구랑 같이 쓰려고` |
| 탐지됐으나 KEEP(정책) | LOCATION·PURCHASE_PATTERN | 4 | `옥천HUB`, `정기배송` |

타입별 n은 커졌지만 대부분 한두 시나리오에서 나온 것이라 타입 단위 결론은 못 냄. 어떤 표현이 새는지 보여 주는 사례로만 씀. 예외는 이름: 시나리오 28개에 걸쳐 고유 이름 277개가 들어가서 표본 의미가 있음. 이름 실패 33건은 `고객주우영` 같은 붙여쓰기(`llmc_sensitive_02` 5건)와 성만 남기고 끊는 partial이 대부분.

**gold 범위 기준 변경(1회)**: 처음 받은 `llm_claude`는 `[[질염이 생겼다고|...]]`처럼 서술어까지 감싼 것이 있었음. 프록시 목적이 "정보를 드러내는 최소 단어를 가리는 것"이라 WRITING_GUIDE에 최소 범위 규칙을 넣고 `[[...]]` 전체에 같은 규칙을 적용함(5곳 수정, 원본은 `llm_claude.v1-wide-gold.yaml`로 보관). 이 변경으로 보호율이 0.745 → 0.782가 됨(`임신`·`질염` partial 4건이 보호로 바뀜). 이후 gold는 결과를 보고 고치지 않음.

**③~⑥ 스크립트 검증(키 없이)**: 실제 LLM 결과는 아직 없음.
- `--l7 real`을 키 없이 돌리면 두 경로 모두 `L7_API_KEY_MISSING`으로 기록되고 채점에서 제외됨. 재실행 시 성공한 id만 건너뜀
- 정답을 알고 있는 가짜 답변 파일로 ③④ 확인: 가명 경로 2건만 틀리게 만들었을 때 분류 정확도 1.000 → 0.833, McNemar 원본만 맞음=2·p=0.500, CFP도 그 2건만 빠짐
- ⑤ 같은 파일로 실행: 같은 답변은 1.000, 틀리게 만든 쪽만 낮아짐(분류 0.922). CPU 약 5분(모델 다운로드 포함)
- ⑥ 라벨 파싱만 확인(JSON·코드블록·평문·모호한 응답→`파싱실패`)

## 5-2. 실제 LLM 중간 실행 (Gemini, 헤드라인 아님)

조건: 코드 `dc4119c`, L7 `gemini-3.1-flash-lite`, `data_v2_p3.jsonl`(템플릿당 3건, 288건), 결과 `~/eval-data/run_real_gemini.jsonl`.
- 288건 중 164건만 두 경로 성공. 처음엔 분당 제한(429)으로 실패 → `--sleep 8` 추가 후 안정. 이어서 Google 503(과부하) 연속, 마지막엔 일일 할당량 소진(429 RESOURCE_EXHAUSTED)으로 중단
- 성공분이 `llm_claude`·`template_claude`에만 있고 `llm_gemini`는 0건(실행 순서 때문). 모델을 섞을 수 없어서 **이 결과는 버리고 Claude Sonnet 5.5로 288건 처음부터 다시 돌림**. 아래는 채점 규칙 변경 근거로만 남김

**strict 채점이 형식 문제로 정확도를 크게 깎음.** Gemini가 "가능/불가만"을 무시하고 `…확인한 결과 **결과: 가능**`, `네, 대상이 맞습니다`처럼 길게 답함. 답이 정답으로 시작해야 정답인 strict에서 llm_claude 원본 경로 정확도가 QA 0.231, 분류 0.441(오답 39건 중 앞 10건을 보니 전부 내용은 맞음).

**채점 규칙 변경 1회(lenient 추가).** 사유: L7 모델이 출력 형식 지시를 따르지 않음. strict 결과도 같이 냄.
- 선택지: `choices.yaml`에 템플릿별로 프롬프트의 보기를 그대로 옮김(답변 보고 정하지 않음)
- 추출 순서: ① `결과:`/`정답:`/`답:` 뒤·`**강조**` 안 → ② 첫 문장 → ③ 마지막 줄. 그 단계에서 선택지가 하나만 남으면 답
- 부정: 선택지 바로 뒤 `않·아니·없`이면 이지선다는 반대 선택지, 아니면 버림(`가능하지 않습니다`→불가). 긴 선택지 우선 매칭(`불가능`을 `가능`으로 안 읽음)
- QA: 금액·날짜·개수는 숫자만 뽑아 대조(`14`=`14일`), 전화·이메일·표기명은 정규화 포함
- 못 정하면 unparsed → 오답, 건수 따로 보고
- **규칙 고정**: `score.py` sha256 `4eb50e29e083…`, `choices.yaml` `6207dbf19eb3…`. 이후 사람 라벨을 보고 고치지 않음
- 검증 계획: Sonnet 결과에서 원본 경로 strict 오답 전체 + strict 정답 중 무작위 20건을 사람이 정답/오답 라벨링 → lenient와 일치율 보고. 라벨은 규칙을 만든 사람(Claude)이 아닌 팀원이 함

Gemini 164건 중간 수치(llm_claude, 참고): strict 원본 0.552 / 가명 0.563, lenient 원본 0.943 / 가명 0.920, loss +0.023 boot[−0.034, +0.091], unparsed 원본 4·가명 7. **lenient로 다시 계산하니 loss가 0이 아니게 나옴** → 보고는 "utility loss 상한 X%p(95%)" 형태로 씀(유의차 없음 ≠ 손실 없음).

**masked_star 비교를 추가함.** 가명 경로 loss가 작아도 "그냥 지우면 품질이 떨어진다"를 보여 줘야 토큰화의 의미가 섬. 같은 탐지 스팬을 `***`로 지워(`고객 ***님 … 주문번호 ***로`) 같은 L7에 보냄. 분류 과제는 값 없이도 판단 가능한 게 많아 차이가 작을 수 있음 → 그럴 땐 equivariant 사실(답변에 값이 들어가야 하는 과제)의 ④ CFP 차이로 보여 줌.

## 5-3. 실제 LLM 결과 (Claude Sonnet 5.5, 288건) — ③④⑤⑥·masked_star

조건: 코드 `dc4119c` + 이 eval 스크립트(lenient 규칙 해시 `score.py` 4eb50e29e083 / `choices.yaml` 6207dbf19eb3), L7 `claude-sonnet-5-5`(MonoGPT 게이트웨이, anthropic 형식), `temperature 0`, `max_tokens 1024`, 프록시 시스템 프롬프트 포함. 데이터 `data_v2_p3.jsonl`(시나리오 96 × 3 = 288건). 결과 `~/eval-data/run_real_sonnet.jsonl`, `masked_sonnet.jsonl`, `score_sonnet.txt`, `bertscore_sonnet.txt`, `judge_gemini-3.5-flash-lite.*`.
- 두 경로 성공 287/288. 실패 1건은 `llmc_reply_03-1` L5 차단(echo와 같은 원인). 일시적 L7 스트림 실패 3건은 재시도로 복구
- 비용: 원장(공식 단가 기준) 합계 **$5.88**(시험 호출 포함, 기준선 $1.41 포함, 상한 $12). MonoGPT 실제 차감액은 미확인
- ② 보호율은 echo와 같은 경향(llm_claude 0.739, llm_gemini 0.711)

**③ Task 정확도 (분류·QA·추출)**

| 그룹 | 채점 | 원본 | 가명(복원) | loss (95% 구간) | McNemar 원본만/가명만 | masked_star | masked loss (95%) |
|---|---|---|---|---|---|---|---|
| llm_claude (n=102) | strict | 0.863 | 0.853 | +1.0%p [0, +2.9] | 1 / 0 | - | - |
| | **lenient** | **0.980** | **0.980** | **0.0%p [−5.9, +5.9]** | 2 / 2 | **0.755** | **+22.5%p [+8.8, +38.2]** |
| llm_gemini (n=72) | strict | 0.639 | 0.583 | +5.6%p [−2.8, +16.7] | 5 / 1 | - | - |
| | **lenient** | **0.958** | **0.958** | **0.0%p (불일치 0쌍)** | 0 / 0 | **0.694** | **+26.4%p [+9.7, +44.4]** |

- 보고 문구: **"가명처리 utility loss 상한 5.9%p(95%, llm_claude). llm_gemini는 두 경로 판정이 갈린 레코드가 0건"**. 유의차 없음을 손실 없음으로 쓰지 않음
- lenient unparsed: 원본 0건, 가명 2건
- strict에서 llm_gemini 분류가 0.333으로 낮은 건 형식 문제(Sonnet도 `일치/불일치`류 지시에 설명을 붙임). lenient는 사람 라벨로 검증 예정
- **masked_star는 추출 과제에서 크게 떨어짐**: llm_claude 추출 1.000 → 0.200, llm_gemini 0.875 → 0.333. 분류는 값 없이도 판단돼서 거의 그대로(0.949 → 0.974). 예상대로 차이는 "답에 값이 들어가야 하는 과제"에서 남

**④ Critical Fact Preservation (lenient)**

| 그룹 | 전체: 원본 / 가명 / masked | equivariant 값형: 원본 / 가명 / masked |
|---|---|---|
| llm_claude | 0.946 / 0.956 / 0.585 | 0.991 / **1.000** / **0.310** (n=113) |
| llm_gemini | 0.951 / 0.959 / 0.667 | 0.917 / **0.950** / **0.350** (n=60) |

- 가명 경로 loss: llm_claude −1.0%p [−3.9, +2.1], llm_gemini −0.8%p [−5.7, +4.1]
- **발표용 핵심**: 답장·요약에 들어가야 할 주문번호·금액·이름 같은 값이 토큰화+역매핑에서는 그대로 돌아오지만(값형 사실 1.000), `***`로 지우면 31%만 남음. "마스킹하면 품질이 떨어진다 → 토큰화로 해결"의 근거
- 가명 쪽이 원본보다 약간 높은 건 원본 답변이 주민번호·회원번호를 "보안상 제외했다"며 일부러 빼는 경우가 있어서(토큰은 그냥 옮겨 적고 역매핑됨)

**원본 재실행 기준선(`baseline.py`, 가명처리 없이 같은 원문을 같은 L7에 한 번 더)**: 가명처리와 무관한 L7 자체 변동(노이즈 바닥)

| 그룹 | 비교 | ③ lenient 판정 갈린 쌍 (원본만/비교만) | ④ CFP 전체 loss | ⑤ BERTScore F1 |
|---|---|---|---|---|
| llm_claude | 원본 vs **원본 재실행** | 0 / 1 (n=102) | 0.0%p [−1.5, +1.4] | **0.847** [0.820, 0.876] |
| | 원본 vs **가명** | 2 / 2 | −1.0%p [−3.9, +2.1] | **0.802** [0.763, 0.839] |
| llm_gemini | 원본 vs **원본 재실행** | 0 / 0 (n=72) | +0.8%p [−1.8, +3.5] | **0.842** [0.820, 0.865] |
| | 원본 vs **가명** | 0 / 0 | −0.8%p [−5.7, +4.1] | **0.797** [0.772, 0.824] |

- ③④: 가명 경로 차이가 기준선 변동과 같은 크기(판정 갈림 몇 건, CFP 구간이 0을 포함). 가명처리로 생긴 손실을 L7 자체 변동과 구분할 수 없는 수준
- ⑤: 가명 경로가 기준선보다 약 0.045 낮음(두 그룹 모두, 구간 거의 안 겹침). 표현이 달라진 건 맞지만 ③④상 결론·핵심 사실은 유지 → 문체·구성 차이로 해석(예: 토큰을 본 LLM이 "회원번호는 노출 필요 없어 제외" 같은 문장을 덜 씀). 단독 근거로는 안 씀

**⑤ BERTScore F1 (원본 답변 vs 복원 답변)**: llm_claude 0.802 boot[0.763, 0.839], llm_gemini 0.797 boot[0.772, 0.824]. 위 기준선과 같이 봄

**⑥ LLM Judge (자유서술 30건, seed 0 무작위, `gemini-3.5-flash-lite`)**
- 순서: `gemini-3.5-flash`(429로 3건 만에 중단, 결과 버림) → `gemini-3.5-flash-lite`(완료). L7(Claude)과 다른 계열
- 최종 라벨: 동치 1 / 경미한 차이 15 / 의미 다름 4 / **불일치(A·B 위치 바꾸면 판정이 달라짐) 10**. 불일치가 1/3이라 Judge 신뢰도가 낮음 → 보조 지표로만 씀. **결정: 사람 재판정·더 강한 Judge 없이 한계로 기재**(lite 모델·무료 할당량 제약, `gemini-3.5-flash`는 429)
- 의미 다름 4건 원인:
  - `llmg_bank_account_03-1` **프록시 원인**: NER이 `김정모`를 `김정`까지만 잡아(partial) 답변이 "김정 님"이 됨 + `계좌로 2~3일`의 `계좌로 2`를 ADDRESS_ROAD로 과탐(5절의 알려진 버그). LLM이 "주소 토큰이 들어가 있다, 확인 필요"라고 직접 지적함
  - `llmg_auth_03-1` **프록시 원인(정당한 손실)**: 원본 경로는 주민번호 앞자리로 "20대 후반이라는데 1970년대생"이라는 모순을 찾았고, 가명 경로는 주민번호가 토큰이라 못 찾음. 값 자체를 봐야 하는 추론은 토큰화로 잃음
  - `address_change-2`, `llmg_customs_03-0` Judge 노이즈: 회원번호·통관부호를 문자에 넣었는지 차이(원본 답변이 보안상 뺌). 결론은 같음

**알려진 과탐(ADDRESS_ROAD, 미수정)**: 조사 `로`/`으로` + 숫자를 도로명으로 잡음(`배송지연으로 3`, `계좌로 2`, `입금으로 1`). 이 288건에서 9건(템플릿 3개)에 끼어 있음. 영향 확인 결과 ② 보호율·③ Task·④ CFP는 **변화 없음**(분류 3건 두 경로 모두 정답, 자유서술 6건 사실 전부 보존). ② precision만 오름(llm_gemini 0.968 → 1.000 예상), ⑥ Judge 1~3건(원인 분리 불가). 일정상 보고서 뒤 별도 PR로 수정하기로 함(숫자 뒤 날짜·수량 단위 제외 조건, ADDRESS_LOT 단위 제외 재사용)

**한계(이 절)**: L7 1개 모델, 템플릿당 3건(클러스터 = 시나리오), Judge 1개 lite 모델·위치 바꾸면 판정 갈림 1/3, lenient 사람 검증 전, 손작성 그룹 없음, 원본 재실행 기준선 1회.

## 6. 남은 것 / 결정 필요

- lenient 검증용 사람 라벨 57건(strict 오답 37 + 정답 표본 20, 순서 섞음): 팀원 작업 중. 채우면 `python eval/label_agree.py --data ~/eval-data/data_v2_p3.jsonl --run ~/eval-data/run_real_sonnet.jsonl --sheet ~/eval-data/label_sheet.tsv`
- ADDRESS_ROAD 과탐 수정: 보고서 뒤 별도 PR(5-3)
- ⑥ 사람 라벨 일치율(κ): 시간 남으면 30건
- 데이터 분담: 손작성(`hand_*`) 작성자. 팀원은 자기 레이어 규칙을 알아서 팀 밖 사람(멘토 등)이 가장 좋음
- 타입 라벨 일치는 안 봄: 보호율은 "가려졌는가"만 셈. 예) gold `ADDRESS_ROAD` 8건은 전부 L3 `ADDRESS`가 통째로 가렸음(L5 겹침 정리 결과, L4 `ADDRESS_ROAD`는 최종 0건). 라벨 정확도가 필요하면 별도 지표로 추가
- gold에 `LOCATION_INFORMAL`·L3 `ADDRESS` 타입으로 표시한 문장은 아직 없음(탐지는 각각 2건·8건 나옴)
- 보고서에 kept(정책 결정)와 missed(탐지 실패)를 분리해서 적을 것
- 차단(fail-closed) 비율을 별도 지표로 보고할 것. 현재 8/310, LOCATION_INFORMAL↔주소 겹침 병합 정책은 L5 담당과 협의 필요
