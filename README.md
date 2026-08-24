# privacy-proxy

이커머스 CS 문맥의 한국어 개인정보를 탐지하고 가명화한 뒤, 외부 LLM API로 중계하는 B2B 프록시 서비스.
자체 LLM 인프라가 없는 기업이 외부 LLM을 쓰면서도 원문 개인정보가 외부로 나가지 않도록 하는 것을 목표로 한다.

## 동작 개요

```
클라이언트 요청
→ 개인정보 탐지(Presidio 규칙 + KLUE-BERT NER)
→ 결합 위험도 평가
→ 가명화(Vault 저장)
→ 외부 LLM 호출
→ 응답 역치환
→ 클라이언트 응답
```

원문과 토큰의 매핑은 서버 내부 Vault(AES-256, Redis)에만 존재하며, 외부로 전송되지 않는다.

## 기술 스택

- Python 3.11+ / FastAPI
- Presidio, KLUE-BERT
- Redis (Vault)
- AWS (ECS/EC2, ElastiCache, KMS, Secrets Manager)
- uv, ruff, pytest, GitHub Actions

## 시작하기

```bash
uv sync
docker compose up -d          # Redis Vault
uv run uvicorn privacy_proxy.main:app --reload
```

## 담당

| 파트 | 담당 | 주요 과제 |
| --- | --- | --- |
| 기본 탐지 (Presidio) | 정민우 | Analyzer/Recognizer 구조 분석, 기본 Regex·NER Recognizer(이름·전화번호·이메일·주소) 구현 |
| 이커머스 특화 탐지 (NER) | 이선학 | KLUE-BERT NER 연동, spaCy 어절 Alignment(조사 분리), 주문번호·고객번호·배송정보 Custom Recognizer |
| 문맥·위험도 평가 | 형지원 | 준식별자 결합 탐지(거주지·연령대·구매패턴 등), Risk Score 산출식, 등급별 차등 정책 |
| 가명화·Vault | 윤채림 | 세션 토큰 치환(대체값·플레이스홀더 이원화), AES-256 Redis Vault, 충돌 회피·세션 일관성·멱등성 |
| 프록시·복원 | 김민석 | Egress 프록시 구축, 외부 LLM API 연동, SSE 버퍼·응답 검사·역치환, 감사 로그(원문/매핑 미저장) |

## 개발 규칙

- 실제 개인정보는 어떤 형태로도 커밋하지 않는다 (테스트 데이터는 반드시 가상값 사용)
- 커밋 전 ruff, pytest 통과 필수
- 주요 설계 결정은 docs/decisions/에 기록한다

## 기여 방법

### 브랜치 전략

```
main (항상 동작 상태, 발표/제출용)
 └─ develop (통합 브랜치)
     ├─ feature/detection            # 기본 탐지 (정민우)
     ├─ feature/detection-ecommerce  # 이커머스 특화 탐지 (이선학)
     ├─ feature/risk-scoring         # 문맥·위험도 평가 (형지원)
     ├─ feature/vault                # 가명화·Vault (윤채림)
     └─ feature/proxy                # 프록시·복원 (김민석)
```

- main 직접 push 금지, develop에서 검증된 것만 merge
- 프록시 스켈레톤을 develop에 먼저 올리고, 나머지는 거기서 feature 브랜치를 생성한다
- 커밋 전 develop 최신으로 rebase
- 최초 1회 `git config core.hooksPath .githooks` 실행 (main/develop 직접 push 방지)

### 커밋 메시지

`[파트태그] 내용` 형식. 예시:

```
[detection] KLUE-BERT 초기 모델 로드 구현
[vault] AES-256 키 파생 로직 추가
[proxy] SSE 응답 버퍼 처리 수정
```

파트태그 목록: detection, detection-ecommerce, risk-scoring, vault, proxy, docs, chore

### PR

- 최소 1명 리뷰 후 merge (본인 파트가 아닌 사람으로 순환 배정)
- CI(ruff, pytest) 통과 필수 — 체크가 빨간 상태로 merge하지 않는다
- develop 최종 merge는 팀장이 확인 후 진행한다
- PR 본문에 구현 내용(1줄) / 테스트 방법 / 의존성 있는 부분을 포함한다

### 로컬 검사

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
```

`pre-commit install`을 한 번 실행해두면 커밋 시 자동으로 검사된다.

## 문서

- 아키텍처: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 설계 결정 기록: [docs/decisions/](docs/decisions/)
