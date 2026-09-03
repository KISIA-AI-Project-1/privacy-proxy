import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DetectedPII(BaseModel):
    """
    [L3, L4 탐지 레이어용]
    개인정보 위치는 Python 슬라이싱 방식 (start_idx 포함, end_idx 미포함)
    검증: raw_prompt[start_idx:end_idx] == original_value
    """

    entity_type: str
    original_value: str
    start_idx: int
    end_idx: int
    layer: str
    confidence: float = 1.0


class ProxyContext(BaseModel):
    """
    [공통 규격] L1~L9 파이프라인 단일 컨텍스트 객체
    """

    # L1 / L2 불변 필드 (생성 후 수정 금지)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_prompt: str = Field(..., frozen=True, exclude=True)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"), frozen=True
    )

    # L1 / L2 가변 필드
    user_role: str = "intern"
    status: str = "success"
    error: str | None = None

    # L3 ~ L5 (탐지 및 채점)
    detected_entities: list[DetectedPII] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)

    risk_level: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    policy_action: str | None = None

    # L6 (가명화 및 볼트)
    anonymized_prompt: str | None = None
    vault_mapping: dict[str, str] = Field(default_factory=dict)
    token_types: dict[str, str] = Field(default_factory=dict)

    # L7 (외부 LLM 통신)
    llm_raw_response: str | None = None

    # L8 (복원)
    final_response: str | None = None

    # L9 (감사 및 모니터링)
    latency_ms: dict[str, float] = Field(default_factory=dict)
