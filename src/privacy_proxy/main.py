"""FastAPI 앱 진입점.

현재는 부팅과 헬스체크만 한다. L1~L9 라우터는 각 담당자가 붙인다.
실행: uv run uvicorn privacy_proxy.main:app --reload --port 8000
"""

from typing import Literal

from fastapi import FastAPI

from privacy_proxy import __version__

app = FastAPI(
    title="privacy-proxy",
    version=__version__,
    description="LLM 프롬프트 개인정보 가명화 프록시",
)


@app.get("/healthz")
async def healthz() -> dict[str, str | Literal["ok"]]:
    """로드밸런서·CI용 헬스체크. 비밀값을 절대 노출하지 않는다."""
    return {"status": "ok", "version": __version__}
