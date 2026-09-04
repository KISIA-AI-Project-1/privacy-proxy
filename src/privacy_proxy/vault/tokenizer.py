from collections import defaultdict


class Tokenizer:
    def __init__(self) -> None:
        # 임시 1단계:
        # 현재는 프로그램 메모리에서 토큰과 원문 매핑을 관리한다.
        # 이후 Redis Vault(store.py)와 연동하여 세션별 매핑을 관리할 예정이다.

        # {entity_type: 현재 번호}
        self._counters: dict[str, int] = defaultdict(int)

        # {(entity_type, original_value): token}
        self._mapping: dict[tuple[str, str], str] = {}

    def get_or_create_token(
        self,
        entity_type: str,
        original_value: str,
    ) -> str:
        """
        임시 1단계:
        같은 entity_type + 원문 값이면 기존 토큰을 반환하고,
        처음 등장한 값이면 새 토큰을 생성한다.

        현재는 메모리 기반이며, 이후 Redis Vault와 연동할 예정이다.
        """

        key = (entity_type, original_value)

        # 이미 존재하면 기존 토큰 반환
        if key in self._mapping:
            return self._mapping[key]

        # 새 번호 생성
        self._counters[entity_type] += 1

        token = f"[{entity_type}_{self._counters[entity_type]:03d}]"

        self._mapping[key] = token

        return token
