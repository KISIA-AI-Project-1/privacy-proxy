"""REG-03-B2-3: synthetic producer-stage validator timeout must fail closed.

Tests patch only a validator method on its real producer class, before a real
L3AnalyzerService is created. This exercises Presidio, the actual L3 producer,
and the production service/adapter boundary; no actual PII or external calls.
"""

import logging

import pytest

from privacy_proxy.l3.registry import PRODUCER_TYPES
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.l3.timeout_guard import L3DependencyTimeoutError
from tests import fixtures

CASES = [
    ("KR_RRN", "RRN_VALID"),
    ("KR_FRN", "FRN_VALID"),
    ("KR_BRN", "BRN_VALID"),
    ("KR_DRIVER_LICENSE", "LICENSE_VALID"),
]
MARKER = "SYNTHETIC_VALIDATOR_TIMEOUT_PRIVATE_MARKER"


@pytest.mark.parametrize("entity,fixture_name", CASES)
def test_valid_number_still_detected(entity, fixture_name):
    value = getattr(fixtures, fixture_name)
    detections = L3AnalyzerService().analyze(value, "synthetic", entities=[entity])
    assert len(detections) == 1
    d = detections[0]
    assert str(d.entity_type) == entity
    assert d.original_value == value
    assert d.confidence is None
    assert value[d.start_idx : d.end_idx] == value


@pytest.mark.parametrize("entity,fixture_name", CASES)
@pytest.mark.parametrize("failure_at", [1, 2])
def test_producer_validator_timeout_is_not_silent(
    entity, fixture_name, failure_at, monkeypatch, caplog
):
    cls = PRODUCER_TYPES[entity]
    original = cls.validate_result
    tracker = {"calls": 0, "triggered": False}

    def failing_validate(self, value):
        tracker["calls"] += 1
        if tracker["calls"] == failure_at:
            tracker["triggered"] = True
            raise TimeoutError(MARKER)
        return original(self, value)

    monkeypatch.setattr(cls, "validate_result", failing_validate)
    service = L3AnalyzerService()  # construct AFTER patch; wrapper must be installed
    value = getattr(fixtures, fixture_name)
    text = " | ".join((value, value, value))

    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(L3DependencyTimeoutError, match="L3_DEPENDENCY_TIMEOUT") as caught,
    ):
        service.analyze(text, "synthetic", entities=[entity])
    assert tracker["triggered"]
    assert MARKER not in str(caught.value)
    assert MARKER not in caplog.text
