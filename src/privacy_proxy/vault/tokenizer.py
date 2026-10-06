"""L6 가역적 토큰화.

입력: session_id, raw_prompt(전체 프롬프트), detected_entities(L3/L4 DetectedPII), policy_action(L5, 요청 전체 정책)
출력: TokenizationResult

처리 방식은 (entity_type, policy_action) 조합으로 결정한다.
  - 직접식별자(이름/연락처/각종 ID/고유식별정보/민감정보): policy 와 무관하게 항상 가역 치환
  - 주소: 기본 일반화(비가역). policy=TOKENIZE 이면 가역 토큰
  - 준식별자(LOCATION/AGE/AGE_GROUP/LOCATION_INFORMAL): L5 가 위험으로 판단해
    TOKENIZE/GENERALIZE 를 내린 경우에만 보호, 그 외 정책이면 그대로 통과

Strategy:
  NATURAL_PSEUDONYM : 이름 -> 자연스러운 가명 (가역)
  TYPE_TOKEN        : 식별자 -> 【PHONE_1】 (가역)
  GENERALIZE        : 더 넓은 범위 값으로 치환 (비가역, Vault 저장 안 함)
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .collision import CollisionGuard
from .crypto import VaultCrypto
from .store import CreateStatus, MappingRecord, VaultStore

MAX_ATTEMPTS = 20


class Strategy(StrEnum):
    NATURAL_PSEUDONYM = "NATURAL_PSEUDONYM"
    TYPE_TOKEN = "TYPE_TOKEN"  # noqa: S105
    GENERALIZE = "GENERALIZE"


@dataclass(frozen=True)
class EntitySpec:
    strategy: Strategy
    prefix: str = ""  # TYPE_TOKEN 접두어
    generalizer: str = ""  # GENERALIZE 함수 이름


def _tok(prefix: str) -> EntitySpec:
    return EntitySpec(Strategy.TYPE_TOKEN, prefix)


def _gen(name: str) -> EntitySpec:
    return EntitySpec(Strategy.GENERALIZE, generalizer=name)


_NATURAL = EntitySpec(Strategy.NATURAL_PSEUDONYM)

# policy 와 무관하게 항상 적용
BASE_SPECS: dict[str, EntitySpec] = {
    "PERSON_KO": _NATURAL,
    "PERSON_EN": _NATURAL,
    "PHONE_NUMBER": _tok("PHONE"),
    "EMAIL_ADDRESS": _tok("EMAIL"),
    "ORDER_ID": _tok("ORDER"),
    "CUSTOMER_ID": _tok("CUSTOMER"),
    "TRACKING_NUMBER": _tok("TRACKING"),
    "CUSTOMS_CLEARANCE_ID": _tok("CUSTOMS"),
    "ACCOUNT_NUMBER": _tok("ACCOUNT"),
    "KR_RRN": _tok("RRN"),
    "KR_PASSPORT": _tok("PASSPORT"),
    "KR_FRN": _tok("FRN"),
    "KR_DRIVER_LICENSE": _tok("LICENSE"),
    "KR_BRN": _tok("BRN"),
    "DATE_OF_BIRTH": _tok("DOB"),
    "SENSITIVE_HEALTH": _tok("HEALTH"),
    "SENSITIVE_RELIGION": _tok("RELIGION"),
    "SENSITIVE_FAMILY": _tok("FAMILY"),
    "SENSITIVE_FINANCIAL": _tok("FINANCIAL"),
}

# policy_action 에 따라 달라지는 타입. "*" 는 policy 가 None/그 외일 때의 기본값(없으면 통과)
POLICY_SPECS: dict[str, dict[str, EntitySpec]] = {
    "ADDRESS": {"*": _gen("address"), "TOKENIZE": _tok("ADDR")},
    "ADDRESS_ROAD": {"*": _gen("address"), "TOKENIZE": _tok("ADDR_ROAD")},
    "ADDRESS_LOT": {"*": _gen("address"), "TOKENIZE": _tok("ADDR_LOT")},
    "ADDRESS_DETAIL": {"*": _gen("address"), "TOKENIZE": _tok("ADDR_DETAIL")},
    "LOCATION": {"TOKENIZE": _tok("LOCATION"), "GENERALIZE": _gen("location")},
    "LOCATION_INFORMAL": {"TOKENIZE": _tok("LOCATION"), "GENERALIZE": _tok("LOCATION")},
    "AGE": {"TOKENIZE": _tok("AGE"), "GENERALIZE": _gen("age")},
    "AGE_GROUP": {"TOKENIZE": _tok("AGE_GROUP")},  # 이미 대략적 값이라 GENERALIZE 는 통과
}

_NAMESPACE_OVERRIDES = {"PERSON_KO": "PERSON", "PERSON_EN": "PERSON"}


def namespace_of(entity_type: str) -> str:
    """정방향 lookup 네임스페이스. 정책이 바뀌어도 같은 원문은 같은 매핑을 찾아야 하므로 정책과 무관."""
    return _NAMESPACE_OVERRIDES.get(entity_type, entity_type)


def is_known(entity_type: str) -> bool:
    return entity_type in BASE_SPECS or entity_type in POLICY_SPECS


def resolve_spec(entity_type: str, policy_action: str | None) -> EntitySpec | None:
    if entity_type in BASE_SPECS:
        return BASE_SPECS[entity_type]
    by_policy = POLICY_SPECS.get(entity_type)
    if by_policy is None:
        return None
    return by_policy.get(policy_action or "", by_policy.get("*"))


# ---------------------------------------------------------------------- 일반화 함수
def _generalize_address(value: str) -> str:
    """앞 2어절(시/도 + 시/군/구)만 남긴다."""
    parts = value.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else "【ADDRESS】"


def _generalize_location(value: str) -> str:
    parts = value.split()
    return parts[0] if parts else value


def _generalize_age(value: str) -> str:
    m = re.search(r"\d{1,3}", value)
    if not m:
        return "【AGE】"
    n = int(m.group())
    return "10세 미만" if n < 10 else f"{n // 10 * 10}대"


GENERALIZERS: dict[str, Callable[[str], str]] = {
    "address": _generalize_address,
    "location": _generalize_location,
    "age": _generalize_age,
}

PERSON_POOL_KO = (
    "홍길동",
    "김하늘",
    "이서연",
    "박지훈",
    "최민준",
    "정수빈",
    "강도윤",
    "윤서아",
    "임지호",
    "한유진",
)
PERSON_POOL_EN = (
    "James Carter",
    "Emily Stone",
    "Michael Reed",
    "Sarah Lane",
    "David Brooks",
    "Laura Hayes",
)
# 풀 소진 후 대체값은 닫는 괄호로 끝나게 해서 '사용자[1]' 이 '사용자[10]' 의 부분문자열이 되지 않게 한다.


class EntityMismatchError(ValueError):
    """탐지 span 과 원문이 어긋남. 메시지에 원문/값은 넣지 않는다(PII 보호)."""


class UnsupportedEntityError(ValueError):
    pass


class PseudonymCollisionError(RuntimeError):
    """가명이 결과 프롬프트에서 의도한 횟수보다 많이 나타남 → 복원 오염 위험이므로 요청을 실패시킨다."""


@dataclass(frozen=True)
class TokenizationResult:
    anonymized_prompt: str
    vault_mapping: dict[str, str]  # 가명 -> 원문. 내부 전용, 로그/외부 전송 금지
    token_types: dict[str, str]  # 가명 -> entity_type
    skipped_types: list[str] = field(default_factory=list)  # 미지원 타입(원문 그대로 남음) — 감사용
    passthrough_types: list[str] = field(default_factory=list)  # 정책상 보호 불필요로 통과한 타입

    def as_tuple(self) -> tuple[str, dict[str, str], dict[str, str]]:
        return self.anonymized_prompt, self.vault_mapping, self.token_types


class Tokenizer:
    def __init__(self, store: VaultStore, crypto: VaultCrypto, *, strict: bool = False) -> None:
        """strict=True 면 미지원 entity_type 을 통과시키지 않고 예외를 던진다(fail-closed)."""
        self.store = store
        self.crypto = crypto
        self.guard = CollisionGuard(store)
        self.strict = strict

    # ------------------------------------------------------------------ 정규화
    @staticmethod
    def normalize(entity_type: str, value: str) -> str:
        v = value.strip()
        if entity_type == "PHONE_NUMBER":
            v = re.sub(r"[\s\-().]", "", v)
            if v.startswith("+82"):
                v = "0" + v[3:].lstrip("0")
            return v
        if entity_type == "EMAIL_ADDRESS":
            return v.lower()
        if entity_type in ("PERSON_KO", "PERSON_EN"):
            return " ".join(v.split()).casefold()
        return v

    @staticmethod
    def _aad(session_id: str, entity_type: str) -> str:
        return f"{session_id}|{namespace_of(entity_type)}"

    # ------------------------------------------------------------------ 가명 후보
    @staticmethod
    def _candidate(entity_type: str, spec: EntitySpec, n: int) -> str:
        if spec.strategy is Strategy.TYPE_TOKEN:
            return f"【{spec.prefix}_{n}】"
        if entity_type == "PERSON_EN":
            return PERSON_POOL_EN[n - 1] if n <= len(PERSON_POOL_EN) else f"User[{n}]"
        return PERSON_POOL_KO[n - 1] if n <= len(PERSON_POOL_KO) else f"사용자[{n}]"

    # ------------------------------------------------------------------ 바인딩
    def _bind(
        self,
        session_id: str,
        raw_prompt: str,
        entity_type: str,
        spec: EntitySpec,
        original: str,
        cache: dict[tuple[str, str], str],
    ) -> str:
        """원문에 대응하는 가명을 돌려준다. 이번 요청에서 안전하게 쓸 수 있는 값이어야 한다."""
        ns = namespace_of(entity_type)
        normalized = self.normalize(entity_type, original)
        cache_key = (ns, normalized)
        if cache_key in cache:
            return cache[cache_key]

        existing = self.store.get_mapping(session_id, ns, normalized)
        if existing is not None:
            if existing.pseudonym not in raw_prompt:
                pseudonym = existing.pseudonym
            else:
                # 기존 가명이 이번 원문에 이미 (진짜 텍스트로) 존재 -> 같은 원문에 alias 를 하나 더 발급
                pseudonym = self._new_alias(session_id, raw_prompt, entity_type, spec, existing)
        else:
            enc = self.crypto.encrypt(original, aad=self._aad(session_id, entity_type))
            pseudonym = self._create(session_id, raw_prompt, entity_type, spec, ns, normalized, enc)

        cache[cache_key] = pseudonym
        return pseudonym

    def _create(
        self,
        session_id: str,
        raw_prompt: str,
        entity_type: str,
        spec: EntitySpec,
        ns: str,
        normalized: str,
        enc: str,
    ) -> str:
        for _ in range(MAX_ATTEMPTS):
            n = self.store.next_counter(session_id, entity_type)
            cand = self._candidate(entity_type, spec, n)
            if not self.guard.is_available(session_id, cand, raw_prompt=raw_prompt):
                continue
            result = self.store.create_mapping(
                session_id, ns, normalized, MappingRecord(entity_type, cand, enc)
            )
            if result.status is CreateStatus.COLLISION:
                continue  # 그 사이 다른 요청이 선점
            if result.record is None:
                raise ValueError("vault create returned no record")
            pseudonym = result.record.pseudonym
            if pseudonym in raw_prompt:  # EXISTING 이 이번 프롬프트와 충돌하는 드문 경우
                return self._new_alias(session_id, raw_prompt, entity_type, spec, result.record)
            return pseudonym
        raise RuntimeError(f"could not allocate pseudonym for {entity_type}")

    def _new_alias(
        self,
        session_id: str,
        raw_prompt: str,
        entity_type: str,
        spec: EntitySpec,
        base: MappingRecord,
    ) -> str:
        for _ in range(MAX_ATTEMPTS):
            n = self.store.next_counter(session_id, entity_type)
            cand = self._candidate(entity_type, spec, n)
            if not self.guard.is_available(session_id, cand, raw_prompt=raw_prompt):
                continue
            if self.store.add_alias(
                session_id, MappingRecord(entity_type, cand, base.original_enc)
            ):
                return cand
        raise RuntimeError(f"could not allocate alias for {entity_type}")

    # ------------------------------------------------------------------ span 정리
    @staticmethod
    def _resolve_overlaps(entities: Iterable[Any]) -> list[Any]:
        """겹치는 탐지는 (더 긴 span, 더 높은 confidence) 우선으로 하나만 남긴다."""

        def priority(entity: Any) -> tuple[int, float, int]:
            confidence = getattr(entity, "confidence", 0.0)
            # H2-R1: an ephemeral sorting rank, not measured confidence.
            # Preserve the canonical None and all non-null conversion behavior.
            rank = 0.0 if confidence is None else float(confidence)
            return (-(entity.end_idx - entity.start_idx), -rank, entity.start_idx)

        ordered = sorted(entities, key=priority)
        kept: list[Any] = []
        for e in ordered:
            if all(e.end_idx <= k.start_idx or e.start_idx >= k.end_idx for k in kept):
                kept.append(e)
        return sorted(kept, key=lambda e: e.start_idx)

    # ------------------------------------------------------------------ 메인
    def anonymize(
        self,
        *,
        session_id: str,
        raw_prompt: str,
        detected_entities: list[Any],
        policy_action: str
        | None = None,  # L5 의 요청 전체 보호 정책 (TOKENIZE / GENERALIZE / 그 외)
    ) -> TokenizationResult:
        vault_mapping: dict[str, str] = {}
        token_types: dict[str, str] = {}
        placements: dict[str, int] = {}
        skipped: list[str] = []
        passthrough: list[str] = []
        pieces: list[str] = []
        cache: dict[tuple[str, str], str] = {}
        cursor = 0

        for e in self._resolve_overlaps(detected_entities):
            start, end, original = e.start_idx, e.end_idx, e.original_value
            entity_type = str(e.entity_type)

            if not (0 <= start < end <= len(raw_prompt)) or raw_prompt[start:end] != original:
                raise EntityMismatchError(
                    f"detected span does not match raw prompt: {entity_type}[{start}:{end}]"
                )

            if not is_known(entity_type):
                if self.strict:
                    raise UnsupportedEntityError(entity_type)
                skipped.append(entity_type)
                continue

            spec = resolve_spec(entity_type, policy_action)
            if spec is None:
                passthrough.append(entity_type)
                continue

            if spec.strategy is Strategy.GENERALIZE:
                replacement = GENERALIZERS[spec.generalizer](original)
            else:
                replacement = self._bind(session_id, raw_prompt, entity_type, spec, original, cache)
                vault_mapping[replacement] = original
                token_types[replacement] = entity_type
                placements[replacement] = placements.get(replacement, 0) + 1

            pieces.append(raw_prompt[cursor:start])
            pieces.append(replacement)
            cursor = end

        pieces.append(raw_prompt[cursor:])
        output = "".join(pieces)

        # 안전망: 가명이 의도한 횟수만큼만 나타나야 한다(인접 문자열과 합쳐져 새로 생기는 경우 등 차단)
        for pseudonym, count in placements.items():
            if output.count(pseudonym) != count:
                raise PseudonymCollisionError(
                    f"pseudonym collision in output: {token_types[pseudonym]}"
                )

        return TokenizationResult(output, vault_mapping, token_types, skipped, passthrough)

    # ------------------------------------------------------------------ L8 복원용
    def reveal(self, session_id: str, pseudonym: str) -> str | None:
        """가명(alias 포함) -> 원문. 없으면 None. 역할 기반 복원 여부는 L8 정책에서 판단."""
        rec = self.store.get_by_pseudonym(session_id, pseudonym)
        if rec is None:
            return None
        return self.crypto.decrypt(rec.original_enc, aad=self._aad(session_id, rec.entity_type))
