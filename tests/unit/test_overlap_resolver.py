from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.schemas import DetectedPII, DetectionTier


def detection(
    entity_type: str,
    value: str,
    start: int,
    end: int,
    *,
    tier: DetectionTier,
    confidence: float = 1.0,
    source: str = "test",
) -> DetectedPII:
    return DetectedPII(
        entity_type=entity_type,
        original_value=value,
        start_idx=start,
        end_idx=end,
        confidence=confidence,
        tier=tier,
        source=source,
    )


def test_direct_address_wins_over_overlapping_informal_location() -> None:
    entities = [
        detection("LOCATION_INFORMAL", "강남구", 4, 7, tier=DetectionTier.MODEL),
        detection("ADDRESS_ROAD", "서울시 강남구", 0, 7, tier=DetectionTier.RULE_ANCHORED),
    ]

    assert [item.entity_type for item in resolve_overlaps(entities)] == ["ADDRESS_ROAD"]


def test_nonoverlapping_address_components_both_survive() -> None:
    entities = [
        detection("ADDRESS_ROAD", "테헤란로", 0, 4, tier=DetectionTier.RULE_ANCHORED),
        detection("ADDRESS_DETAIL", "101동 202호", 8, 17, tier=DetectionTier.RULE_ANCHORED),
    ]

    assert [item.entity_type for item in resolve_overlaps(entities)] == [
        "ADDRESS_ROAD",
        "ADDRESS_DETAIL",
    ]


def test_touching_spans_are_not_overlaps() -> None:
    entities = [
        detection("PERSON_KO", "홍길동", 0, 3, tier=DetectionTier.MODEL),
        detection("LOCATION_INFORMAL", "서울", 3, 5, tier=DetectionTier.MODEL),
    ]

    assert len(resolve_overlaps(entities)) == 2


def test_resolution_is_input_order_independent() -> None:
    entities = [
        detection(
            "LOCATION_INFORMAL",
            "강남 쪽",
            0,
            4,
            tier=DetectionTier.MODEL,
            confidence=0.8,
            source="ner",
        ),
        detection(
            "ADDRESS_ROAD",
            "강남 쪽 테헤란로",
            0,
            9,
            tier=DetectionTier.RULE_ANCHORED,
            confidence=0.7,
            source="recognizer",
        ),
    ]

    forward = resolve_overlaps(entities)
    backward = resolve_overlaps(list(reversed(entities)))
    assert forward == backward
    assert [item.entity_type for item in forward] == ["ADDRESS_ROAD"]
