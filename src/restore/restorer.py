from privacy_proxy.schemas import ProxyContext


async def restore_l8(context: ProxyContext) -> ProxyContext:
    """
    [L8 레이어] AI 답변 내의 가명화 토큰을 원본 개인정보로 역치환하여 복원합니다.
    """
    if context.status == "failed" or not context.llm_raw_response:
        return context

    try:
        restored_text = context.llm_raw_response

        # vault_mapping를 순회하며 토큰을 원본 데이터로 덮어쓰기
        if context.vault_mapping:
            for token, original_value in context.vault_mapping.items():
                restored_text = restored_text.replace(token, original_value)

        context.final_response = restored_text

    except Exception as e:
        context.status = "failed"
        context.error = f"L8 역치환 복원 실패: {e!s}"

    return context
