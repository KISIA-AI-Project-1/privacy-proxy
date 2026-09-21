import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# 엔티티타입 Enum추가
class EntityType(StrEnum):
    # [유지] L3 기본 통신/계정 식별자
    PHONE = "PHONE"
    EMAIL = "EMAIL"

    # 법적/행정 식별자 (L3/L4 공통 대응)
    RRN = "RRN"  # 주민등록번호 / 외국인등록번호
    BUSINESS_REGISTRATION_NUMBER = "BUSINESS_REGISTRATION_NUMBER"  # 사업자등록번호

    # L4 NER 엔터티
    PERSON_KO = "PERSON_KO"  # NAME -> 한국어 인명(조사 분리 대응)
    LOCATION_INFORMAL = "LOCATION_INFORMAL"  # 비정형 지역 표기

    # L4 이커머스 도메인 Recognizer 8종
    CUSTOMS_CLEARANCE_ID = "CUSTOMS_CLEARANCE_ID"  # 개인통관고유부호
    ORDER_ID = "ORDER_ID"
    TRACKING_NUMBER = "TRACKING_NUMBER"
    CUSTOMER_ID = "CUSTOMER_ID"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    ADDRESS_ROAD = "ADDRESS_ROAD"  # ADDRESS 세분화 (도로명)
    ADDRESS_LOT = "ADDRESS_LOT"  # ADDRESS 세분화 (지번)
    ADDRESS_DETAIL = "ADDRESS_DETAIL"  # ADDRESS 세분화 (동/호수 등 상세)

    # L4 민감정보(Sensitive) 4종 사전 반영
    SENSITIVE_HEALTH = "SENSITIVE_HEALTH"
    SENSITIVE_RELIGION = "SENSITIVE_RELIGION"
    SENSITIVE_FAMILY = "SENSITIVE_FAMILY"
    SENSITIVE_FINANCIAL = "SENSITIVE_FINANCIAL"

    # 예외 및 미분류 처리용
    ETC = "ETC"


# -------------------------------------------------------------
# 1. [L4] 추가 요청 사항
# deterministic > rule_anchored > model > candidate
# -------------------------------------------------------------


class DetectionTier(StrEnum):
    DETERMINISTIC = "deterministic"
    RULE_ANCHORED = "rule_anchored"
    MODEL = "model"
    CANDIDATE = "candidate"


# -------------------------------------------------------------
# 1. [L1] 사용자 인증/인가 컨텍스트
# -------------------------------------------------------------
class UserContext(BaseModel):
    user_id: str
    department: str
    role: str
    allowed_models: list[str] = Field(default_factory=lambda: ["gpt-5", "gpt-4o-mini"])
    restore_level: str = "default"


# -------------------------------------------------------------
# 2. [L2] 요청 파싱 및 세그먼트 모델
# -------------------------------------------------------------
class TextSegment(BaseModel):
    segment_id: str
    path: str
    role: str | None = "user"
    text: str


class ParsedRequest(BaseModel):
    vendor: str = "openai"
    model: str
    segments: list[TextSegment]
    original_body: dict[str, Any]


# -------------------------------------------------------------
# 3. [L3 ~ L4] 탐지 레이어 모델 (기존 유지)
# -------------------------------------------------------------
class DetectedPII(BaseModel):
    entity_type: EntityType | str
    original_value: str
    start_idx: int
    end_idx: int
    confidence: float = Field(..., ge=0.0, le=1.0)
    segment_id: str = "seg-1"

    normalized: str = ""  # 요청 사항 기본값 제공용

    # 우선순위
    tier: DetectionTier = DetectionTier.MODEL
    source: str = Field(default="unknown", description="탐지 출처 (예: L3_Regex, L4_BERT)")

    # 기존 mock 코드 및 하위 호환성을 위한 속성 입니다
    @property
    def layer(self) -> str:
        return self.source


# -------------------------------------------------------------
# 4. [L1~L9 공통] 파이프라인 단일 컨텍스트
# -------------------------------------------------------------
class ProxyContext(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        frozen=True,
    )

    # L1 결과 보관
    user: UserContext | None = None
    user_role: str = "intern"

    # L2 결과 보관
    parsed_request: ParsedRequest | None = None
    raw_prompt: str = Field(default="", exclude=True)  # 기존 호환용

    # L3 ~ L5 (탐지/위험도)
    detected_entities: list[DetectedPII] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0)
    risk_level: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    policy_action: str | None = None

    # L6 (가명화)
    anonymized_prompt: str | None = None
    vault_mapping: dict[str, str] = Field(default_factory=dict)
    token_types: dict[str, str] = Field(default_factory=dict)

    # L7 ~ L9 (재조립, 중계, 복원, 감사)
    reconstructed_body: dict[str, Any] = Field(default_factory=dict)
    llm_raw_response: Any = Field(default=None, exclude=True)
    final_response: Any = Field(default=None, exclude=True)
    final_response_log: str | None = Field(default=None, exclude=True)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    status: str = "success"
    error: str | None = None
