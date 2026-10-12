"""L6 Vault 저장소.

Redis 키 구조 (모든 키에 TTL):
  vault:{sid}:f:{HMAC(ns, normalized)}  -> MappingRecord(JSON)   # 원문 -> 가명 (정방향)
  vault:{sid}:r:{HMAC(pseudonym)}       -> MappingRecord(JSON)   # 가명 -> 원문 (역방향, L8 복원용)
  vault:{sid}:c:{entity_type}           -> 정수 카운터 (INCR)

원문은 record.original_enc(AES-GCM 암호문)로만 저장된다.
"생성"은 Lua 스크립트로 원자적으로 수행 → 동시 요청에서도 같은 가명이 두 번 발급되지 않는다.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from .crypto import VaultCrypto

if TYPE_CHECKING:  # redis 는 런타임 import 하지 않아도 테스트 가능
    from redis import Redis

DEFAULT_TTL_SECONDS = 60 * 60 * 24
_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


class CreateStatus(Enum):
    CREATED = "created"
    EXISTING = "existing"  # 동시 요청이 먼저 만들어 둔 매핑이 있음
    COLLISION = "collision"  # 이 가명은 이미 다른 원문이 사용 중


@dataclass(frozen=True)
class MappingRecord:
    entity_type: str
    pseudonym: str
    original_enc: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | bytes) -> MappingRecord:
        return cls(**json.loads(raw))


@dataclass(frozen=True)
class CreateResult:
    status: CreateStatus
    record: MappingRecord | None  # COLLISION 이면 None


class VaultStore(Protocol):
    def get_mapping(
        self, session_id: str, namespace: str, normalized: str
    ) -> MappingRecord | None: ...
    def get_by_pseudonym(self, session_id: str, pseudonym: str) -> MappingRecord | None: ...
    def pseudonym_exists(self, session_id: str, pseudonym: str) -> bool: ...
    def create_mapping(
        self, session_id: str, namespace: str, normalized: str, record: MappingRecord
    ) -> CreateResult: ...
    def add_alias(self, session_id: str, record: MappingRecord) -> bool: ...
    def next_counter(self, session_id: str, entity_type: str) -> int: ...
    def delete_session(self, session_id: str) -> int: ...


class _KeyBuilder:
    def __init__(self, crypto: VaultCrypto) -> None:
        self._crypto = crypto

    @staticmethod
    def _check(session_id: str) -> str:
        # SCAN 패턴 주입/키 오염 방지
        if not _SESSION_RE.match(session_id):
            raise ValueError("invalid session_id")
        return session_id

    def fwd(self, sid: str, ns: str, normalized: str) -> str:
        return f"vault:{self._check(sid)}:f:{self._crypto.lookup_key(sid, ns, normalized)}"

    def rev(self, sid: str, pseudonym: str) -> str:
        return f"vault:{self._check(sid)}:r:{self._crypto.lookup_key(sid, 'PSEUDONYM', pseudonym)}"

    def ctr(self, sid: str, entity_type: str) -> str:
        return f"vault:{self._check(sid)}:c:{entity_type}"

    def session_pattern(self, sid: str) -> str:
        return f"vault:{self._check(sid)}:*"


# KEYS[1]=fwd, KEYS[2]=rev / ARGV[1]=record json, ARGV[2]=ttl
# return {code, json}: 1=created, 0=existing, 2=collision
_CREATE_LUA = """
local existing = redis.call('GET', KEYS[1])
if existing then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
  return {0, existing}
end
if redis.call('EXISTS', KEYS[2]) == 1 then
  return {2, ''}
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[2])
return {1, ARGV[1]}
"""


class RedisVaultStore:
    """`Redis(decode_responses=False)` 클라이언트를 받는다."""

    def __init__(
        self, client: Redis[bytes], crypto: VaultCrypto, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> None:
        self._r = client
        self._keys = _KeyBuilder(crypto)
        self._ttl = ttl_seconds
        self._create = client.register_script(_CREATE_LUA)

    def _load(self, key: str) -> MappingRecord | None:
        raw = self._r.get(key)
        if raw is None:
            return None
        self._r.expire(key, self._ttl)  # sliding TTL
        return MappingRecord.from_json(raw)

    def get_mapping(self, session_id: str, namespace: str, normalized: str) -> MappingRecord | None:
        rec = self._load(self._keys.fwd(session_id, namespace, normalized))
        if rec is not None:
            self._r.expire(self._keys.rev(session_id, rec.pseudonym), self._ttl)
            # 카운터가 매핑보다 먼저 만료되면 번호가 1부터 다시 시작해 기존 가명과 충돌한다.
            self._r.expire(self._keys.ctr(session_id, rec.entity_type), self._ttl)
        return rec

    def get_by_pseudonym(self, session_id: str, pseudonym: str) -> MappingRecord | None:
        return self._load(self._keys.rev(session_id, pseudonym))

    def pseudonym_exists(self, session_id: str, pseudonym: str) -> bool:
        return bool(self._r.exists(self._keys.rev(session_id, pseudonym)))

    def create_mapping(
        self, session_id: str, namespace: str, normalized: str, record: MappingRecord
    ) -> CreateResult:
        code, raw = self._create(
            keys=[
                self._keys.fwd(session_id, namespace, normalized),
                self._keys.rev(session_id, record.pseudonym),
            ],
            args=[record.to_json(), self._ttl],
        )
        if int(code) == 2:
            return CreateResult(CreateStatus.COLLISION, None)
        status = CreateStatus.CREATED if int(code) == 1 else CreateStatus.EXISTING
        return CreateResult(status, MappingRecord.from_json(raw))

    def add_alias(self, session_id: str, record: MappingRecord) -> bool:
        """기존 원문에 가명을 하나 더 붙인다(역방향 키만 추가). 이미 쓰는 가명이면 False."""
        return bool(
            self._r.set(
                self._keys.rev(session_id, record.pseudonym),
                record.to_json(),
                nx=True,
                ex=self._ttl,
            )
        )

    def next_counter(self, session_id: str, entity_type: str) -> int:
        key = self._keys.ctr(session_id, entity_type)
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._ttl)
        value, _ = pipe.execute()
        return int(value)

    def delete_session(self, session_id: str) -> int:
        keys = list(self._r.scan_iter(match=self._keys.session_pattern(session_id), count=500))
        return int(self._r.delete(*keys)) if keys else 0


class InMemoryVaultStore:
    """단위 테스트 / 로컬 개발용. 스레드 안전, TTL 없음."""

    def __init__(self, crypto: VaultCrypto) -> None:
        self._keys = _KeyBuilder(crypto)
        self._data: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._lock = threading.Lock()

    def get_mapping(self, session_id: str, namespace: str, normalized: str) -> MappingRecord | None:
        raw = self._data.get(self._keys.fwd(session_id, namespace, normalized))
        return MappingRecord.from_json(raw) if raw else None

    def get_by_pseudonym(self, session_id: str, pseudonym: str) -> MappingRecord | None:
        raw = self._data.get(self._keys.rev(session_id, pseudonym))
        return MappingRecord.from_json(raw) if raw else None

    def pseudonym_exists(self, session_id: str, pseudonym: str) -> bool:
        return self._keys.rev(session_id, pseudonym) in self._data

    def create_mapping(
        self, session_id: str, namespace: str, normalized: str, record: MappingRecord
    ) -> CreateResult:
        fwd = self._keys.fwd(session_id, namespace, normalized)
        rev = self._keys.rev(session_id, record.pseudonym)
        with self._lock:
            if fwd in self._data:
                return CreateResult(CreateStatus.EXISTING, MappingRecord.from_json(self._data[fwd]))
            if rev in self._data:
                return CreateResult(CreateStatus.COLLISION, None)
            self._data[fwd] = self._data[rev] = record.to_json()
        return CreateResult(CreateStatus.CREATED, record)

    def add_alias(self, session_id: str, record: MappingRecord) -> bool:
        rev = self._keys.rev(session_id, record.pseudonym)
        with self._lock:
            if rev in self._data:
                return False
            self._data[rev] = record.to_json()
        return True

    def next_counter(self, session_id: str, entity_type: str) -> int:
        key = self._keys.ctr(session_id, entity_type)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]

    def delete_session(self, session_id: str) -> int:
        prefix = f"vault:{self._keys._check(session_id)}:"
        with self._lock:
            targets = [k for k in (*self._data, *self._counters) if k.startswith(prefix)]
            for k in targets:
                self._data.pop(k, None)
                self._counters.pop(k, None)
        return len(targets)
