"""환경 변수 로딩. 값 목록과 설명은 .env.example 참고."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """프록시 설정.

    비밀값은 전부 SecretStr로 감싼다. repr/로그/트레이스백에 원본이 찍히면
    L9(감사 로그에 원문 미기록) 원칙이 깨진다.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    proxy_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")

    vault_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    vault_encryption_key: SecretStr = SecretStr("")
    vault_ttl_seconds: int = Field(default=3600, gt=0)

    log_level: str = "INFO"
    demo_mode: bool = False
    l4_ner_enabled: bool = False
    l4_ner_model_path: str = ""

    audit_s3_enabled: bool = False
    audit_s3_bucket: str = ""
    audit_s3_region: str = "ap-northeast-2"


@lru_cache
def get_settings() -> Settings:
    """프로세스당 한 번만 읽는다. FastAPI 의존성으로 주입해 쓴다."""
    return Settings()
