# 1. 파이썬 3.11 공식 리눅스 이미지 사용
FROM python:3.11-slim

# 2. 파이썬 버퍼링을 꺼서 로그가 터미널에 실시간으로 찍히도록 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. 컨테이너 내부의 작업 폴더 설정
WORKDIR /app

# 4. 필수 리눅스 패키지 설치 (빌드 도구 등)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 5. 의존성 파일 먼저 복사 (캐시 효율 최적화)
# pyproject.toml이 루트에 있으므로 복사합니다.
COPY pyproject.toml .

# 6. pip 최신화 및 프로젝트 패키지 설치
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# 7. 실제 소스코드 및 필요한 설정 파일들을 컨테이너 내부로 복사
COPY src/ /app/src/

# 8. 컨테이너가 열어둘 포트 명시 (FastAPI 기본 포트)
EXPOSE 8000

# 9. 컨테이너가 시작될 때 FastAPI 서버를 실행하는 명령어
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]