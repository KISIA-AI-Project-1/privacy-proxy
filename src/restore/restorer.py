from collections.abc import AsyncGenerator

from privacy_proxy.schemas import ProxyContext


async def restore_l8(context: ProxyContext) -> ProxyContext:
    """
    [L8: 역치환 복원 레이어 (스트리밍 업그레이드)]
    """
    if context.status == "failed" or not context.llm_raw_response:
        return context

    try:
        mapping = context.vault_mapping

        # 글자 수가 긴 가명부터 정렬하여 오치환 방지
        sorted_fake_keys = sorted(mapping.keys(), key=len, reverse=True) if mapping else []

        # 가장 긴 가명화 키워드의 길이 계산
        max_fake_len = len(sorted_fake_keys[0]) if sorted_fake_keys else 0

        async def _streaming_buffer() -> AsyncGenerator[str, None]:
            buffer = ""

            async for chunk in context.llm_raw_response:
                buffer += chunk

                for fake_pii in sorted_fake_keys:
                    if fake_pii in buffer:
                        real_pii = mapping[fake_pii]
                        buffer = buffer.replace(fake_pii, real_pii)

                # [슬라이딩 윈도우]
                if len(buffer) > max_fake_len:
                    safe_chunk = buffer[:-max_fake_len]
                    yield safe_chunk
                    buffer = buffer[-max_fake_len:]

            if buffer:
                for fake_pii in sorted_fake_keys:
                    if fake_pii in buffer:
                        real_pii = mapping[fake_pii]
                        buffer = buffer.replace(fake_pii, real_pii)
                yield buffer

        context.final_response = _streaming_buffer()

    except Exception:
        context.status = "failed"
        context.error = "L8_RESTORE_FAILED"

    return context
