from itertools import permutations

import pytest

from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.schemas import DetectedPII, DetectionTier


def detection(text, kind, anchor=None, confidence=0.4, source="L4_RECOGNIZER_TRACKING"):
    value = "112412345601"
    start = text.index(value)
    return DetectedPII(
        entity_type=kind,
        original_value=value,
        normalized=value,
        start_idx=start,
        end_idx=start + len(value),
        confidence=confidence,
        tier=DetectionTier.DETERMINISTIC
        if kind == "KR_DRIVER_LICENSE"
        else DetectionTier.RULE_ANCHORED,
        source=source,
        anchor_text=anchor,
        anchor_start=text.index(anchor) if anchor else None,
        anchor_end=text.index(anchor) + len(anchor) if anchor else None,
    )


def test_direct_anchor_not_lost_to_null_json_tie():
    text = "송장번호: 112412345601"
    anchored = detection(text, "TRACKING_NUMBER", "송장번호")
    missing = detection(text, "TRACKING_NUMBER")
    license = detection(text, "KR_DRIVER_LICENSE", source="L3_Regex")
    for sequence in permutations([anchored, missing, license]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [anchored]


def test_indirect_type_cannot_replace_direct_type_after_license_exception():
    text = "송장번호는 별도입니다. 주문번호: 112412345601"
    direct = detection(text, "ORDER_ID", "주문번호", source="L4_RECOGNIZER_ORDER")
    indirect = detection(text, "TRACKING_NUMBER", "송장번호")
    license = detection(text, "KR_DRIVER_LICENSE", source="L3_Regex")
    for sequence in permutations([direct, indirect, license]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [direct]


def test_unknown_source_confidence_does_not_change_selected_evidence():
    text = "송장번호: 112412345601"
    anchored = detection(text, "TRACKING_NUMBER", "송장번호", confidence=0.1, source="unknown")
    missing = detection(text, "TRACKING_NUMBER", confidence=0.9, source="unknown")
    first = resolve_overlaps([anchored, missing], raw_prompt=text)[0]
    second = resolve_overlaps(
        [
            anchored.model_copy(update={"confidence": 0.9}),
            missing.model_copy(update={"confidence": 0.1}),
        ],
        raw_prompt=text,
    )[0]
    assert first.anchor_text == second.anchor_text


@pytest.mark.parametrize("source", ["unknown", ""])
@pytest.mark.parametrize("scores", [(0.1, 0.9), (None, 0.9)])
def test_indistinguishable_uncomparable_scores_fail_in_every_order(source, scores):
    text = "송장번호: 112412345601"
    first = detection(text, "TRACKING_NUMBER", confidence=scores[0], source=source)
    second = first.model_copy(update={"confidence": scores[1]})
    for sequence in permutations([first, second]):
        with pytest.raises(ValueError, match="ambiguous uncomparable confidence"):
            resolve_overlaps(list(sequence), raw_prompt=text)
    assert first.confidence == scores[0]
    assert second.confidence == scores[1]


def test_equal_duplicates_are_safe_and_measured_scores_still_compare():
    text = "송장번호: 112412345601"
    first = detection(text, "TRACKING_NUMBER", "송장번호", confidence=0.1)
    high = first.model_copy(update={"confidence": 0.9})
    for sequence in permutations([first, high, high.model_copy()]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [high]
    unknown = first.model_copy(update={"source": "unknown"})
    assert resolve_overlaps([unknown, unknown.model_copy()], raw_prompt=text) == [unknown]


def test_discarded_ambiguous_duplicates_do_not_fail_request():
    text = "송장번호: 112412345601"
    first = detection(text, "TRACKING_NUMBER", confidence=0.1, source="unknown")
    second = first.model_copy(update={"confidence": 0.9})
    winner = detection(text, "KR_DRIVER_LICENSE", source="L3_Regex")
    for sequence in permutations([first, second, winner]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [winner]


def test_identical_keys_in_separate_segments_do_not_compare_confidence():
    text = "송장번호: 112412345601"
    first = detection(text, "TRACKING_NUMBER", confidence=0.1, source="unknown")
    second = first.model_copy(update={"confidence": 0.9, "segment_id": "seg-2"})
    for sequence in permutations([first, second]):
        assert resolve_overlaps(list(sequence), raw_prompt=text) == [first, second]


async def test_ambiguous_score_failure_preserves_input_at_l5_boundary():
    from privacy_proxy.risk.stage import run_l5_risk_scoring
    from privacy_proxy.schemas import ProxyContext

    text = "송장번호: 112412345601"
    first = detection(text, "TRACKING_NUMBER", confidence=0.1, source="unknown")
    second = first.model_copy(update={"confidence": 0.9})
    for sequence in permutations([first, second]):
        original = list(sequence)
        context = await run_l5_risk_scoring(
            ProxyContext(raw_prompt=text, detected_entities=original)
        )
        assert context.status == "failed"
        assert context.error == "L5_VALIDATION_FAILED"
        assert context.detected_entities == original
        assert context.entity_policies == []
        assert context.policy_action is None
