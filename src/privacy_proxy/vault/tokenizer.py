"""L6 가역적 토큰화.

입력: session_id, raw_prompt(전체 프롬프트), detected_entities(L3/L4 DetectedPII),
      policy_action(L5, 요청 전체 정책), entity_policies(L5, 항목별 정책)
출력: TokenizationResult

처리 방식은 (entity_type, action) 조합으로 결정한다. 원문 내용(키워드 사전 등)은 보지 않는다.
action 은 항목별 정책(entity_policies)이 있으면 그것을, 없으면 요청 단위 policy_action 을 쓴다.
  - 직접식별자(이름/연락처/각종 ID/고유식별정보/민감정보): action 과 무관하게 항상 가역 치환
  - 주소: 기본 일반화(비가역). action=TOKENIZE 이면 가역 토큰
  - 준식별자(LOCATION/AGE/AGE_GROUP/LOCATION_INFORMAL):
    L5 가 위험으로 판단해 TOKENIZE/GENERALIZE 를 내린 경우에만 보호, 그 외면 그대로 통과
  - 상품(PRODUCT_ITEM): TOKENIZE/GENERALIZE 모두 '상품' 으로 비가역 일반화
    (Vault 저장 안 함 -> L8 복원 제외). ALLOW/None 이면 통과.
  - 항상 통과: PURCHASE_PATTERN(정기배송 여부 등)
    시나리오 A 에서 "업무상 유지할 정보"라서 L6 는 action 과 무관하게 건드리지 않는다.
    L5 위험 점수에는 그대로 반영된다.

조사 보정: 대체어 끝 글자가 한글이면 뒤에 붙은 조사를 받침에 맞게 고친다
(김철수가 -> 홍길동이, 임신테스트기를 -> 상품을). 한글이 아닌 대체어(【PHONE_1】 등)는 그대로 둔다.

Strategy:
  NATURAL_PSEUDONYM : 이름 -> 자연스러운 가명 (가역)
  TYPE_TOKEN        : 식별자 -> 【PHONE_1】 (가역). 타입 고정 힌트가 있으면 【HEALTH_1:건강정보】
  GENERALIZE        : 더 넓은 범위 값으로 치환 (비가역, Vault 저장 안 함)

span 별 처리 결과는 TokenizationResult.entity_actions 로 돌려준다(TOKENIZE/GENERALIZE/KEEP/SKIPPED).
(segment_id, start_idx, end_idx) 가 L5 EntityPolicy 와 같은 키라 좌표로 조인할 수 있다.
원문 값은 담지 않는다.

힌트는 entity_type 별 고정 문구만 쓴다(원문 내용과 무관 -> 어떤 입력에도 동일하게 동작).
의미 보존형 상품 일반화는 L4 가 카테고리를 DetectedPII 로 제공하게 되면 그때 추가한다.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
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
    hint: str = ""  # TYPE_TOKEN 에 붙일 타입 고정 분류 설명(선택)


def _tok(prefix: str, hint: str = "") -> EntitySpec:
    return EntitySpec(Strategy.TYPE_TOKEN, prefix, hint=hint)


def _gen(name: str) -> EntitySpec:
    return EntitySpec(Strategy.GENERALIZE, generalizer=name)


_NATURAL = EntitySpec(Strategy.NATURAL_PSEUDONYM)

# action 과 무관하게 항상 적용
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
    "SENSITIVE_HEALTH": _tok("HEALTH", "건강정보"),
    "SENSITIVE_SEX_LIFE": _tok("SEX_LIFE"),
}

# action 에 따라 달라지는 타입. "*" 는 action 이 None/그 외일 때의 기본값(없으면 통과)
# ADDRESS_ROAD/LOT/DETAIL 은 L4 가 시·구 없이 "월드컵북로4길 77" 처럼 조각으로 내보내므로
# 비가역 기본값은 어절을 남기는 일반화가 아니라 전체 마스킹("address_fragment")이다.
POLICY_SPECS: dict[str, dict[str, EntitySpec]] = {
    "ADDRESS": {"*": _gen("address"), "TOKENIZE": _tok("ADDR")},
    "ADDRESS_ROAD": {"*": _gen("address_fragment"), "TOKENIZE": _tok("ADDR_ROAD")},
    "ADDRESS_LOT": {"*": _gen("address_fragment"), "TOKENIZE": _tok("ADDR_LOT")},
    "ADDRESS_DETAIL": {"*": _gen("address_fragment"), "TOKENIZE": _tok("ADDR_DETAIL")},
    "LOCATION": {"TOKENIZE": _tok("LOCATION"), "GENERALIZE": _gen("location")},
    # GENERALIZE 는 LOCATION 과 같은 비가역 일반화. L3 LOCATION 과 L4 NER 가 같은 구간을
    # 중복 탐지해도 어느 쪽이 남든 결과가 같아야 한다.
    # (예전에는 가역 토큰이라 L5 GENERALIZE 인데 【LOCATION_1】 로 나가고 L8 이 복원했다)
    "LOCATION_INFORMAL": {"TOKENIZE": _tok("LOCATION"), "GENERALIZE": _gen("location")},
    "AGE": {"TOKENIZE": _tok("AGE"), "GENERALIZE": _gen("age")},
    "AGE_GROUP": {"TOKENIZE": _tok("AGE_GROUP")},  # 이미 대략적 값이라 GENERALIZE 는 통과
    # 상품명: 공통 표현 '상품' 으로 비가역 일반화(Vault 저장 안 함, L8 복원 제외).
    # 요청 단위 정책이 TOKENIZE 로 폴백돼도 가역 토큰이 나가지 않게 둘 다 일반화한다.
    # ALLOW/None 이면 통과. 카테고리 보존(예: '헤어케어 제품')은 taxonomy 가 생기면 추가한다.
    "PRODUCT_ITEM": {"TOKENIZE": _gen("product"), "GENERALIZE": _gen("product")},
    # 정기배송 여부는 시나리오 A 의 "업무상 유지할 정보". 팀 합의(L6 항상 통과, L5 점수엔 반영).
    # 빈 dict -> resolve_spec 이 None -> passthrough(KEEP). is_known 은 True 라 strict 에서도 예외 없음.
    # 주의: 이 키를 삭제하면 strict 모드에서 UnsupportedEntityError 로 L6 전체가 실패한다.
    "PURCHASE_PATTERN": {},
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
_PROVINCE_ENDINGS = ("특별자치도", "특별자치시", "특별시", "광역시", "도")
_PROVINCE_ABBREVIATIONS = {
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
}
_ADMIN_ENDINGS = ("특별자치도", "특별자치시", "특별시", "광역시", "도", "시", "군", "구")


def _generalize_address(value: str) -> str:
    """앞쪽의 시·도/시·군·구 어절(최대 2개)만 남긴다. 도로명·번지 등이 나오면 거기서 멈춘다."""
    kept: list[str] = []
    for part in value.split():
        if len(kept) < 2 and part.endswith(_ADMIN_ENDINGS):
            kept.append(part)
        else:
            break
    return " ".join(kept) if kept else "【ADDRESS】"


def _generalize_address_fragment(value: str) -> str:
    """도로명+번호, 지번, 동·호·층 같은 주소 조각은 상위 지역을 알 수 없으므로 전체를 가린다."""
    return "【ADDRESS】"


def _generalize_location(value: str) -> str:
    """지역을 시·도 수준으로 낮춘다.

    - 여러 어절("서울 마포구 신림동"): 첫 어절(시·도)만 남긴다.
    - 단일 어절: L3 LOCATION 은 행정단위 하나씩 나오므로(예: "관악구", "신림동")
      시·도 수준이면 그대로 두고, 그보다 세부 단위(시·군·구, 읍·면·동 등)는
      상위 단위를 알 수 없으므로 "【LOCATION】" 으로 가린다.
    """
    parts = value.split()
    if not parts:
        return "【LOCATION】"
    if len(parts) >= 2:
        return parts[0]
    compact = parts[0]
    if compact.endswith(_PROVINCE_ENDINGS):
        return compact

    if compact in _PROVINCE_ABBREVIATIONS:
        return compact
    return "【LOCATION】"


def _generalize_age(value: str) -> str:
    m = re.search(r"\d{1,3}", value)
    if not m:
        return "【AGE】"
    n = int(m.group())
    return "10세 미만" if n < 10 else f"{n // 10 * 10}대"


def _generalize_product(value: str) -> str:
    """상품명은 공통 표현으로 바꾼다. 카테고리는 남기지 않는다(taxonomy 없음)."""
    return "상품"


GENERALIZERS: dict[str, Callable[[str], str]] = {
    "address": _generalize_address,
    "address_fragment": _generalize_address_fragment,
    "location": _generalize_location,
    "age": _generalize_age,
    "product": _generalize_product,
}


# ---------------------------------------------------------------------- 조사 보정
# 대체어 받침에 맞춰 조사를 보정한다. (받침 있을 때, 받침 없을 때)
_JOSA_PAIRS = (
    ("이에요", "예요"),
    ("이라고", "라고"),
    ("이랑", "랑"),
    ("이나", "나"),
    ("으로", "로"),
    ("은", "는"),
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
)
_JOSA_PAIR_OF = {form: pair for pair in _JOSA_PAIRS for form in pair}
_JOSA_FORMS = sorted(_JOSA_PAIR_OF, key=len, reverse=True)  # 긴 것부터
# 뒤에 글자가 이어지면("가격", "이메일", "인데요") 조사가 아니다.
_JOSA_RE = re.compile(
    "(" + "|".join(re.escape(form) for form in _JOSA_FORMS) + r")(?![0-9A-Za-z_가-힣])"
)
_RIEUL = 8  # 종성 ㄹ 인덱스


def _josa_for(replacement: str, josa: str) -> str | None:
    """대체어 끝 글자 받침에 맞는 조사. 끝 글자가 한글 음절이 아니면 None(보정 안 함)."""
    code = ord(replacement[-1]) - 0xAC00
    if not 0 <= code <= 11171:
        return None
    jong = code % 28
    with_batchim, without_batchim = _JOSA_PAIR_OF[josa]
    if with_batchim == "으로":
        return "로" if jong in (0, _RIEUL) else "으로"
    return without_batchim if jong == 0 else with_batchim


def _fix_josa(replacement: str, text: str, pos: int, limit: int) -> tuple[str, int]:
    """text[pos:] 앞에 붙은 조사를 대체어에 맞게 고친다. (고친 조사, 소비한 글자 수).

    다음 탐지 span(limit) 을 침범하지 않는다. 보정할 게 없으면 ("", 0).
    """
    match = _JOSA_RE.match(text, pos)
    if match is None or match.end() > limit:
        return "", 0
    fixed = _josa_for(replacement, match.group(1))
    if fixed is None:
        return "", 0
    return fixed, match.end() - pos


# 이름 가명 풀: 고전 소설 인물 이름(한국어), 대표 가명(영어).
# - 실제 고객 이름과 겹칠 가능성이 낮고, LLM 이 가명임을 쉽게 알아챈다.
# - 일상 단어와 같은 이름(예: 장화=부츠, 방자)은 제외한다. 응답에 일반 단어로 나와도
#   L8 이 실제 이름으로 복원해 버리기 때문이다.
# - 부정적 이미지의 인물(놀부, 변학도 등)과 호칭("박씨부인")은 "OO 고객님"으로 나오면 어색해 제외한다.
# 알려진 한계: LLM 이 프롬프트에 없는 같은 이름을 예시로 쓰면 L8 이 그것도 복원한다
#   (CollisionGuard 는 프롬프트만 검사한다). 외부 유출이 아니라 답변 품질 문제다.
PERSON_POOL_KO = (
    "홍길동",
    "성춘향",
    "이몽룡",
    "심청",
    "흥부",
    "전우치",
    "허생",
    "콩쥐",
    "홍련",
    "향단",
    "월매",
    "임꺽정",
    "옹고집",
    "김원전",
    "최척",
    "서화담",
    "유충렬",
    "조웅",
    "이대봉",
    "양소유",
)
PERSON_POOL_EN = (
    "John Doe",
    "Jane Doe",
    "John Smith",
    "Jane Smith",
    "Richard Roe",
    "Mary Major",
)
# 풀 소진 후 대체값은 닫는 괄호로 끝나게 해서 '사용자[1]' 이 '사용자[10]' 의 부분문자열이 되지 않게 한다.


class EntityMismatchError(ValueError):
    """탐지 span 과 원문이 어긋남. 메시지에 원문/값은 넣지 않는다(PII 보호)."""


class UnsupportedEntityError(ValueError):
    pass


class PseudonymCollisionError(RuntimeError):
    """가명이 결과 프롬프트에서 의도한 횟수보다 많이 나타남 → 복원 오염 위험이므로 요청을 실패시킨다."""


class EntityActionKind(StrEnum):
    TOKENIZE = "TOKENIZE"  # 가역 토큰/가명으로 치환
    GENERALIZE = "GENERALIZE"  # 비가역 일반화
    KEEP = "KEEP"  # 정책상 보호 불필요 -> 원문 유지
    SKIPPED = "SKIPPED"  # 미지원 타입(non-strict) -> 원문 유지


@dataclass(frozen=True)
class EntityAction:
    """raw_prompt 좌표 기준 span 별 L6 처리 결과. 원문 값은 담지 않는다(PII 보호).

    (segment_id, start_idx, end_idx) 는 L5 EntityPolicy 와 같은 키라 좌표로 조인할 수 있다.
    """

    segment_id: str
    start_idx: int
    end_idx: int
    entity_type: str
    action: EntityActionKind


@dataclass(frozen=True)
class TokenizationResult:
    anonymized_prompt: str
    vault_mapping: dict[str, str]  # 가명 -> 원문. 내부 전용, 로그/외부 전송 금지
    token_types: dict[str, str]  # 가명 -> entity_type
    skipped_types: list[str] = field(default_factory=list)  # 미지원 타입(원문 그대로 남음) — 감사용
    passthrough_types: list[str] = field(default_factory=list)  # 정책상 보호 불필요로 통과한 타입
    entity_actions: list[EntityAction] = field(
        default_factory=list
    )  # span 별 처리 결과(시연 표시용)

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
        if entity_type in (
            "PRODUCT_ITEM",
            "SENSITIVE_HEALTH",
            "SENSITIVE_SEX_LIFE",
        ):
            # 공백/대소문자 차이로 같은 값이 다른 토큰이 되지 않게 한다.
            return " ".join(v.split()).casefold()
        return v

    @staticmethod
    def _aad(session_id: str, entity_type: str) -> str:
        return f"{session_id}|{namespace_of(entity_type)}"

    # ------------------------------------------------------------------ 가명 후보
    @staticmethod
    def _candidate(entity_type: str, spec: EntitySpec, n: int) -> str:
        if spec.strategy is Strategy.TYPE_TOKEN:
            label = f"{spec.prefix}_{n}"
            return f"【{label}:{spec.hint}】" if spec.hint else f"【{label}】"
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
    # ------------------------------------------------------------------ 메인
    def anonymize(
        self,
        *,
        session_id: str,
        raw_prompt: str,
        detected_entities: list[Any],
        policy_action: str | None = None,
        entity_policies: Mapping[tuple[str, int, int], str] | None = None,
    ) -> TokenizationResult:
        """entity_policies: L5 항목별 정책. 키는 (segment_id, start_idx, end_idx).

        항목별 값이 있으면 그것을, 없으면 요청 단위 policy_action 을 쓴다.
        직접식별자(BASE_SPECS)와 PURCHASE_PATTERN 은 어느 쪽이든 정책과 무관하다.
        """
        vault_mapping: dict[str, str] = {}
        token_types: dict[str, str] = {}
        placements: dict[str, int] = {}
        skipped: list[str] = []
        passthrough: list[str] = []
        actions: list[EntityAction] = []
        pieces: list[str] = []
        cache: dict[tuple[str, str], str] = {}
        cursor = 0

        resolved = self._resolve_overlaps(detected_entities)

        for index, e in enumerate(resolved):
            start, end, original = e.start_idx, e.end_idx, e.original_value
            entity_type = str(e.entity_type)
            segment_id = getattr(e, "segment_id", "seg-1")
            next_start = (
                resolved[index + 1].start_idx if index + 1 < len(resolved) else len(raw_prompt)
            )

            if not (0 <= start < end <= len(raw_prompt)) or raw_prompt[start:end] != original:
                raise EntityMismatchError(
                    f"detected span does not match raw prompt: {entity_type}[{start}:{end}]"
                )

            if not is_known(entity_type):
                if self.strict:
                    raise UnsupportedEntityError(entity_type)

                skipped.append(entity_type)
                actions.append(
                    EntityAction(
                        segment_id,
                        start,
                        end,
                        entity_type,
                        EntityActionKind.SKIPPED,
                    )
                )
                continue

            action = policy_action
            if entity_policies is not None:
                action = entity_policies.get(
                    (segment_id, start, end),
                    policy_action,
                )

            # PRODUCT_ITEM은 정책이 누락되거나 ALLOW로 전달되어도 원문을 통과시키지 않는다.
            if entity_type == "PRODUCT_ITEM" and action not in (
                "TOKENIZE",
                "GENERALIZE",
            ):
                action = "GENERALIZE"

            spec = resolve_spec(entity_type, action)

            if spec is None:
                passthrough.append(entity_type)
                actions.append(
                    EntityAction(
                        segment_id,
                        start,
                        end,
                        entity_type,
                        EntityActionKind.KEEP,
                    )
                )
                continue

            resume = end

            if spec.strategy is Strategy.GENERALIZE:
                replacement = GENERALIZERS[spec.generalizer](original)
                actions.append(
                    EntityAction(
                        segment_id,
                        start,
                        end,
                        entity_type,
                        EntityActionKind.GENERALIZE,
                    )
                )

            else:
                replacement = self._bind(
                    session_id,
                    raw_prompt,
                    entity_type,
                    spec,
                    original,
                    cache,
                )

                record = self.store.get_by_pseudonym(
                    session_id,
                    replacement,
                )

                if record is None:
                    raise ValueError(f"vault mapping not found for pseudonym: {replacement}")

                # Vault에 실제 저장된 원문을 사용한다.
                # 같은 전화번호의 표기 형식이 달라도 reveal() 결과와 일치한다.
                vault_mapping[replacement] = self.crypto.decrypt(
                    record.original_enc,
                    aad=self._aad(session_id, record.entity_type),
                )

                token_types[replacement] = entity_type
                placements[replacement] = placements.get(replacement, 0) + 1

                actions.append(
                    EntityAction(
                        segment_id,
                        start,
                        end,
                        entity_type,
                        EntityActionKind.TOKENIZE,
                    )
                )

            # 매핑 등록 뒤에 붙이므로 vault_mapping 키(가명)에는 조사가 섞이지 않는다.
            josa, consumed = _fix_josa(
                replacement,
                raw_prompt,
                end,
                next_start,
            )

            if consumed:
                replacement += josa
                resume = end + consumed

            pieces.append(raw_prompt[cursor:start])
            pieces.append(replacement)
            cursor = resume

        pieces.append(raw_prompt[cursor:])
        output = "".join(pieces)

        # 안전망: 가명이 의도한 횟수만큼만 나타나야 한다.
        for pseudonym, count in placements.items():
            if output.count(pseudonym) != count:
                raise PseudonymCollisionError(
                    f"pseudonym collision in output: {token_types[pseudonym]}"
                )

        return TokenizationResult(
            output,
            vault_mapping,
            token_types,
            skipped,
            passthrough,
            actions,
        )
        # ------------------------------------------------------------------ L8 복원용

    def reveal(self, session_id: str, pseudonym: str) -> str | None:
        """가명(alias 포함) -> 원문. 없으면 None."""
        rec = self.store.get_by_pseudonym(session_id, pseudonym)
        if rec is None:
            return None
        return self.crypto.decrypt(
            rec.original_enc,
            aad=self._aad(session_id, rec.entity_type),
        )
