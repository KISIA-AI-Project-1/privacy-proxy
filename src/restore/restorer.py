from privacy_proxy.schemas import ProxyContext


async def restore_l8(context: ProxyContext) -> ProxyContext:
    """
    [L8: 역치환 복원 레이어]
    """
    if context.status == "failed" or not context.llm_raw_response:
        return context

    try:
        restored_text = context.llm_raw_response
        mapping = context.vault_mapping

        if mapping:  # 글자 수가 긴 가명부터 정렬
            sorted_fake_keys = sorted(mapping.keys(), key=len, reverse=True)

            for fake_pii in sorted_fake_keys:
                real_pii = mapping[fake_pii]

                # 단어 경계(\b)를 쓰지 않고 replace를 써야 조사 파괴 없이 대체 가능
                restored_text = restored_text.replace(fake_pii, real_pii)

        context.final_response = restored_text

    except Exception as e:
        context.status = "failed"
        context.error = f"L8 역치환 복원 실패: {e!s}"

    return context
