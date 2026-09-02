# 기여 방법

## 브랜치 전략

```
main (항상 동작 상태, 발표/제출용)
 └─ develop (통합 브랜치)
     ├─ feature/detection            # 기본 탐지 (정민우)
     ├─ feature/detection-ecommerce  # 이커머스 특화 탐지 (이선학)
     ├─ feature/risk-scoring         # 문맥·위험도 평가 (형지원)
     ├─ feature/vault                # 가명화·Vault (윤채림)
     └─ feature/proxy                # 프록시·복원 (김민석)
```

- `main` 직접 push 금지. `develop`에서 검증된 것만 merge한다.
- 프록시 스켈레톤을 `develop`에 먼저 올리고, 나머지는 거기서 feature 브랜치를 생성한다.
- 커밋 전 `develop` 최신으로 rebase한다.
- 최초 1회 `git config core.hooksPath .githooks`를 실행한다. main/develop 직접 push를 막고, pre-commit 훅(ruff, gitleaks, mypy, pytest-cov)도 이걸로 함께 등록된다.

## 커밋 메시지

`[파트태그] 내용` 형식.

```
[detection] KLUE-BERT 초기 모델 로드 구현
[vault] AES-256 키 파생 로직 추가
[proxy] SSE 응답 버퍼 처리 수정
```

파트태그 목록: `detection`, `detection-ecommerce`, `risk-scoring`, `vault`, `proxy`, `docs`, `chore`

## PR

- 최소 1명 리뷰 후 merge한다 (본인 파트가 아닌 사람으로 순환 배정).
- CI(ruff, pytest) 통과 필수 — 체크가 빨간 상태로 merge하지 않는다.
- `develop` 최종 merge는 팀장이 확인 후 진행한다.
- PR 본문에 구현 내용(1줄) / 테스트 방법 / 의존성 있는 부분을 포함한다.

## 로컬 검사

```bash
uv run ruff check .
uv run ruff format .
uv run pytest
```

`core.hooksPath`를 설정해뒀다면 커밋·push 시 자동으로 검사된다.
`pre-commit install`은 쓰지 않는다 — `core.hooksPath`가 설정돼 있으면 pre-commit이 설치를 거부한다.
훅 목록은 [.pre-commit-config.yaml](.pre-commit-config.yaml) 참고.

## 개발 규칙

- 실제 개인정보는 어떤 형태로도 커밋하지 않는다. 테스트 데이터는 반드시 가상값을 쓴다.
- 감사 로그에 원문과 매핑을 남기지 않는다.
- `.env`는 커밋하지 않는다.
- 주요 설계 결정은 `docs/decisions/`에 기록한다.
