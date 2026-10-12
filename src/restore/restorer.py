from collections.abc import AsyncGenerator, AsyncIterable
from time import perf_counter
from typing import cast

from privacy_proxy.config import get_settings
from privacy_proxy.schemas import ProxyContext


async def restore_l8(context: ProxyContext) -> ProxyContext:
    """가명화된 응답을 청크 경계를 보존하며 복원한다."""
    if context.status != "success" or context.llm_raw_response is None:
        return context

    # 요청의 복원 매핑을 별도로 보관한다.
    mapping: dict[str, str] = dict(context.vault_mapping)

    if any(not key for key in mapping):
        context.status = "failed"
        context.error = "L8_INVALID_MAPPING"
        return context

    fake_keys = sorted(mapping, key=len, reverse=True)

    source = cast(
        AsyncIterable[str],
        context.llm_raw_response,
    )

    def consume_buffer(
        buffer: str,
        *,
        final: bool,
    ) -> tuple[str, str]:
        """출력 가능한 부분과 다음 청크까지 보관할 부분을 나눈다."""
        output: list[str] = []
        position = 0

        while position < len(buffer):
            remaining = buffer[position:]

            if not final and any(
                len(remaining) < len(key) and key.startswith(remaining) for key in fake_keys
            ):
                break

            matched_key = next(
                (key for key in fake_keys if buffer.startswith(key, position)),
                None,
            )

            if matched_key is not None:
                output.append(mapping[matched_key])
                position += len(matched_key)
            else:
                output.append(buffer[position])
                position += 1

        return "".join(output), buffer[position:]

    async def restored_stream() -> AsyncGenerator[str, None]:
        buffer = ""

        try:
            async for chunk in source:
                if not isinstance(chunk, str):
                    raise TypeError("unexpected upstream chunk type")
                if get_settings().demo_mode:
                    context.upstream_response_text += chunk

                if not mapping:
                    if chunk:
                        yield chunk
                    continue

                buffer += chunk
                started = perf_counter()
                ready, buffer = consume_buffer(
                    buffer,
                    final=False,
                )
                context.latency_ms["L8_processing"] = (
                    context.latency_ms.get("L8_processing", 0.0) + (perf_counter() - started) * 1000
                )

                if ready:
                    yield ready

            if buffer:
                started = perf_counter()
                ready, _ = consume_buffer(
                    buffer,
                    final=True,
                )
                context.latency_ms["L8_processing"] = (
                    context.latency_ms.get("L8_processing", 0.0) + (perf_counter() - started) * 1000
                )
                if ready:
                    yield ready

        except Exception:
            if context.status == "success":
                context.status = "failed"
                context.error = "L8_STREAM_FAILED"
            raise
        finally:
            context.latency_ms["L8_processing"] = round(
                context.latency_ms.get("L8_processing", 0.0), 3
            )

    context.final_response = restored_stream()
    return context
