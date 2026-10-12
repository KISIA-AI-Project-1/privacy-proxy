"""L6 가명 충돌 회피.

가명이 "사용 가능"하려면:
  1) 현재 프롬프트 원문에 이미 그 문자열이 없어야 한다.
     (원문에 진짜 '홍길동'이 있는데 가명도 '홍길동'이면, 복원 때 원문 홍길동까지 바뀐다)
  2) 같은 세션에서 다른 원문이 이미 쓰고 있지 않아야 한다.
최종 원자성은 store.create_mapping 이 보장하고, 여기는 사전 필터다.
"""

from __future__ import annotations

from .store import VaultStore


class CollisionGuard:
    def __init__(self, store: VaultStore) -> None:
        self._store = store

    def is_available(self, session_id: str, pseudonym: str, *, raw_prompt: str) -> bool:
        if pseudonym in raw_prompt:
            return False
        return not self._store.pseudonym_exists(session_id, pseudonym)
