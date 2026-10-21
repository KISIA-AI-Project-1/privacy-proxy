import pytest

from privacy_proxy.l4_adapter import adapt_klue_span, translate_segment_detection
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


@pytest.mark.parametrize(
    ("label", "expected"),
    [("PS", "PERSON_KO"), ("LC", "LOCATION_INFORMAL")],
)
def test_klue_labels_map_to_canonical_global_detections(
    label: str,
    expected: str,
) -> None:
    detection = adapt_klue_span(
        label=label,
        segment_text="홍길동에게",
        start_idx=0,
        end_idx=3,
        confidence=0.91,
        segment_id="seg-2",
        offset_base=8,
    )

    assert detection.entity_type == expected
    assert detection.original_value == "홍길동"
    assert (detection.start_idx, detection.end_idx) == (8, 11)
    assert detection.tier is DetectionTier.MODEL


def test_recognizer_detection_is_translated_from_segment_to_raw_prompt() -> None:
    local = DetectedPII(
        entity_type="ORDER_ID",
        original_value="123456",
        start_idx=4,
        end_idx=10,
        confidence=0.72,
        segment_id="seg-2",
        normalized="123456",
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_RECOGNIZER_ORDER",
    )

    global_detection = translate_segment_detection(local, offset_base=12)
    context = ProxyContext(
        raw_prompt="x" * 16 + "123456",
        detected_entities=[global_detection],
    )

    assert (global_detection.start_idx, global_detection.end_idx) == (16, 22)
    context.validate_detected_spans()


def test_unknown_klue_label_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported KLUE"):
        adapt_klue_span(
            label="OG",
            segment_text="기관",
            start_idx=0,
            end_idx=2,
            confidence=0.5,
            segment_id="seg-1",
            offset_base=0,
        )


@pytest.mark.parametrize("offset_base", [0, 12])
def test_anchor_coordinates_follow_detection_offset(offset_base: int) -> None:
    local = DetectedPII(
        entity_type="TRACKING_NUMBER",
        original_value="112412345601",
        start_idx=5,
        end_idx=17,
        confidence=None,
        tier=DetectionTier.RULE_ANCHORED,
        source="L4_RECOGNIZER_TRACKING",
        anchor_text="송장번호",
        anchor_start=0,
        anchor_end=4,
    )

    translated = translate_segment_detection(local, offset_base=offset_base)

    assert translated.start_idx == 5 + offset_base
    assert translated.end_idx == 17 + offset_base
    assert translated.anchor_text == "송장번호"
    assert translated.anchor_start == offset_base
    assert translated.anchor_end == 4 + offset_base

    assert local.start_idx == 5
    assert local.anchor_start == 0
