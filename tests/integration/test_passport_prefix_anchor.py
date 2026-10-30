"""Real L3 passport/L4 customer producers through L5, without models or L7."""

from itertools import permutations

import pytest
from l4.recognizers import find_customer_id
from presidio_analyzer.predefined_recognizers import KrPassportRecognizer

from privacy_proxy.l3.tier_mapping import tier_for
from privacy_proxy.l4_adapter import translate_segment_detection
from privacy_proxy.risk.stage import run_l5_risk_scoring
from privacy_proxy.schemas import DetectedPII, ProxyContext


@pytest.mark.parametrize("second_value", ["M12345678", "M87654321"])
@pytest.mark.parametrize(
    "template,expected_types",
    [
        ("여권번호 {first} 고객번호 {second}", ["KR_PASSPORT", "CUSTOMER_ID"]),
        ("고객번호 {first} 여권번호 {second}", ["CUSTOMER_ID", "KR_PASSPORT"]),
        ("여권번호: {first} 고객번호: {second}", ["KR_PASSPORT", "CUSTOMER_ID"]),
        ("여권번호는 {first}이고 고객번호는 {second}입니다", ["KR_PASSPORT", "CUSTOMER_ID"]),
        ("여권번호 {first}\n고객번호 {second}", ["KR_PASSPORT", "CUSTOMER_ID"]),
    ],
)
async def test_each_value_keeps_its_preceding_label(
    template: str, expected_types: list[str], second_value: str
) -> None:
    segment = template.format(first="M12345678", second=second_value)
    prefix = "이전 메시지\n"
    raw = prefix + segment
    producer = KrPassportRecognizer(supported_language="ko")
    hits = sorted(producer.analyze(raw, ["KR_PASSPORT"]), key=lambda hit: hit.start)
    assert len(hits) == 2
    passports = [
        DetectedPII(
            entity_type=hit.entity_type,
            original_value=raw[hit.start : hit.end],
            start_idx=hit.start,
            end_idx=hit.end,
            confidence=hit.score,
            source="L3_Regex",
            tier=tier_for(producer, hit.entity_type, raw[hit.start : hit.end]),
        )
        for hit in hits
    ]
    customers = [
        translate_segment_detection(entity, offset_base=len(prefix))
        for entity in find_customer_id(segment)
    ]
    assert customers
    for sequence in permutations([*passports, *customers]):
        result = await run_l5_risk_scoring(
            ProxyContext(raw_prompt=raw, detected_entities=list(sequence))
        )
        assert result.status == "success"
        # Compare positions, not just strings: both occurrences may have the same value.
        assert [
            (entity.start_idx, entity.end_idx, str(entity.entity_type))
            for entity in result.detected_entities
        ] == [(hit.start, hit.end, kind) for hit, kind in zip(hits, expected_types, strict=True)]
        assert all(policy.action == "TOKENIZE" for policy in result.entity_policies)
