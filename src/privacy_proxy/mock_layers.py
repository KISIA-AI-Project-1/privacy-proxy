import re

from .schemas import DetectedPII, ProxyContext


async def mock_l3_detection(context: ProxyContext) -> ProxyContext:
    "[정민우님] L3: 기본 개인정보 정규식 탐지"
    try:
        phone_pattern = r"\d{2,3}-\d{3,4}-\d{4}"
        for match in re.finditer(phone_pattern, context.raw_prompt):
            context.detected_entities.append(
                DetectedPII(
                    entity_type="PHONE",
                    original_value=match.group(),
                    start_idx=match.start(),
                    end_idx=match.end(),
                    layer="L3_Regex",
                    confidence=1.0,
                )
            )
    except Exception as e:
        context.status = "failed"
        context.error = f"L3_Error: {e!s}"

    return context


async def mock_l4_detection_ecommerce(context: ProxyContext) -> ProxyContext:
    "[이선학님] L4: 이커머스 특화 데이터 탐지"
    try:
        order_pattern = r"ORD-\d+"
        for match in re.finditer(order_pattern, context.raw_prompt):
            context.detected_entities.append(
                DetectedPII(
                    entity_type="ORDER_ID",
                    original_value=match.group(),
                    start_idx=match.start(),
                    end_idx=match.end(),
                    layer="L4_Ecommerce",
                    confidence=0.95,
                )
            )
    except Exception as e:
        context.status = "failed"
        context.error = f"L4_Error: {e!s}"

    return context


async def mock_l5_risk_scoring(context: ProxyContext) -> ProxyContext:
    """[형지원님] L5: 초안 알고리즘 기반 위험도 평가 및 채점"""
    try:
        unique_entities = {e.original_value: e for e in context.detected_entities}.values()
        qis_count = len(unique_entities)

        if qis_count == 0:
            context.risk_score = 0.0
            return context

        base_score = qis_count * 1.5
        count_score = min(0.5 * (qis_count - 1), 2.0)
        rarity_score = 1.0  # 임시 상수값
        interaction_score = 1.0 if qis_count >= 2 else 0.0  # 2개 이상 결합 시 시너지

        raw_score = base_score + count_score + rarity_score + interaction_score

        final_score = raw_score * 20.0

        context.risk_score = max(0.0, min(100.0, final_score))

    except Exception as e:
        context.status = "failed"
        context.error = f"L5_Error: {e!s}"

    return context


async def mock_l6_vault_tokenization(context: ProxyContext) -> ProxyContext:
    "[윤채림님] L6: 토큰화 및 Vault 매핑 구축"
    try:
        text = context.raw_prompt

        sorted_entities = sorted(context.detected_entities, key=lambda x: x.start_idx, reverse=True)

        token_counts: dict[str, int] = {}
        for entity in sorted_entities:
            token_counts[entity.entity_type] = token_counts.get(entity.entity_type, 0) + 1
            token = f"<{entity.entity_type}_{token_counts[entity.entity_type]}>"

            text = text[: entity.start_idx] + token + text[entity.end_idx :]

            context.vault_mapping[token] = entity.original_value
            context.token_types[token] = entity.entity_type

        context.anonymized_prompt = text
    except Exception as e:
        context.status = "failed"
        context.error = f"L6_Error: {e!s}"

    return context
