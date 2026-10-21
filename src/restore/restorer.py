import re
from collections.abc import AsyncGenerator, AsyncIterable
from time import perf_counter
from typing import cast

from privacy_proxy.config import get_settings
from privacy_proxy.schemas import ProxyContext

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
_JOSA_FORMS = sorted(_JOSA_PAIR_OF, key=len, reverse=True)
_JOSA_RE = re.compile(
    "(" + "|".join(re.escape(form) for form in _JOSA_FORMS) + r")(?![0-9A-Za-z_가-힣])"
)
_JOSA_LOOKAHEAD = max(map(len, _JOSA_FORMS)) + 1


def _restore_name_josa(
    original: str,
    following: str,
    *,
    final: bool,
) -> tuple[str, int] | None:
    """원래 이름에 맞는 조사와 소비할 글자 수를 반환한다.

    None은 조사와 그 다음 글자가 올 때까지 기다리라는 뜻이다.
    """
    if not original:
        return "", 0

    code = ord(original[-1]) - 0xAC00
    if not 0 <= code <= 11171:
        return "", 0

    if not final and len(following) < _JOSA_LOOKAHEAD:
        return None

    match = _JOSA_RE.match(following)
    if match is None:
        return "", 0

    jong = code % 28
    with_batchim, without_batchim = _JOSA_PAIR_OF[match.group(1)]

    if with_batchim == "으로":
        corrected = "로" if jong in (0, 8) else "으로"
    else:
        corrected = without_batchim if jong == 0 else with_batchim

    return corrected, match.end()


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

    name_keys = {
        key for key in mapping if context.token_types.get(key) in {"PERSON_KO", "PERSON_EN"}
    }

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
                original = mapping[matched_key]
                next_position = position + len(matched_key)
                josa = ""
                consumed = 0

                if matched_key in name_keys:
                    correction = _restore_name_josa(
                        original,
                        buffer[next_position:],
                        final=final,
                    )

                    if correction is None:
                        break

                    josa, consumed = correction

                output.append(original + josa)
                position = next_position + consumed
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
