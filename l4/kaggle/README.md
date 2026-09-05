# 캐글에서 학습 돌리기

로컬 CPU로는 4개 run에 약 19시간이 걸린다(GPU 없음, 실측 2.7초/스텝).
캐글 T4에서는 40~60분이면 끝나고, `Save & Run All` 로 돌리면 노트북을 꺼도
서버에서 계속 돈다.

## 순서

1. **코드 업로드** — 저장소 루트에서 zip을 만든다.

   ```bash
   zip -r l4_ner.zip l4 -x "l4/kaggle/*" -x "*__pycache__*"
   ```

   캐글 `Datasets` → `New Dataset` → 업로드 → 이름 `l4-ner`.

   > 저장소가 private이라 `git clone` 에는 GitHub 토큰이 필요하다. 개인정보
   > 취급 프로젝트에 외부 서비스로 토큰을 넘기지 않는 편이 낫다. 그래서
   > 데이터셋 업로드를 기본 경로로 둔다. 토큰 방식도 노트북에 대안으로
   > 들어 있다(`Add-ons` → `Secrets` 에 `GITHUB_TOKEN` 등록).

2. **노트북 업로드** — `Code` → `New Notebook` → `File` → `Import Notebook`
   으로 [klue_ner_train.ipynb](klue_ner_train.ipynb) 를 올린다.

3. **오른쪽 패널 설정**

   | 항목 | 값 |
   | --- | --- |
   | Accelerator | GPU T4 x2 (또는 P100) |
   | **Internet** | **On** — 꺼져 있으면 데이터셋 다운로드에서 실패한다 |

4. **Add Input** 으로 1번에서 만든 `l4-ner` 데이터셋을 붙인다.

5. `Save Version` → **`Save & Run All (Commit)`**.
   브라우저를 닫아도 서버에서 끝까지 돈다.

## 노트북이 하는 일

| 셀 | 내용 |
| --- | --- |
| 1 | GPU 확인 (없으면 즉시 중단) |
| 2 | 코드 로드 (데이터셋 우선, 없으면 clone) |
| 3 | 의존성 (`seqeval` 만 추가 설치) |
| 4 | **평가 경로 자체 검증** — 정답을 통과시켜 상한 F1 ≥ 0.95 확인 |
| 5 | 4개 run 학습 |
| 6 | 요약 표 + 그림 3장 |
| 7 | 조사 경계 확인 |
| 8 | 산출물 정리 (기준선 모델만 남김) |

4번 셀이 중요하다. 상한이 0.73 근처로 나오면 엔티티 내부 공백 잇기가 깨진
것이고, 그대로 학습하면 모델이 멀쩡해도 F1이 0.73을 넘지 못한다.

## 버전 차이

캐글 이미지의 transformers 버전이 로컬과 다를 수 있다.
`build_training_arguments()` 가 시그니처를 보고 `eval_strategy` /
`evaluation_strategy`, `warmup_ratio` / `warmup_steps` 를 알아서 맞춘다.
GPU가 잡히면 `fp16` 도 자동으로 켠다.

## 결과 가져오기

`outputs/` 에 run별로 남는다.

```
outputs/
├── summary.csv                     run 간 비교 (F1, PS recall, 지연시간)
├── figures/                        그림 3장
└── klue-ner-base-e3/
    ├── metrics.json
    ├── log_history.csv             epoch별 지표
    └── model/                      기준선 가중치 (약 400MB)
```

`model/` 은 저장소에 커밋하지 않는다(`.gitignore` 로 막혀 있다).
다음 주 `alignment/` 작업에 필요하면 캐글 Output에서 내려받아 로컬
`outputs/klue-ner-base-e3/model/` 에 둔다.

## 지연시간 수치 해석

GPU에서 잰 값과 CPU에서 잰 값이 다르다. 로컬 CPU 실측은 **90ms/건**이었다.
L4를 CPU로 서빙할 계획이면 CPU 수치가 현실적인 값이고, GPU 서빙이면 GPU
수치를 쓴다. 어느 쪽인지 정해지기 전까지는 두 값을 같이 기록해 둔다.
