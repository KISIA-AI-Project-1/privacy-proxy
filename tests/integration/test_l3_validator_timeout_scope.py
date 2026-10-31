"""REG-03-B2-6A: actual producer timeout must be atomic across entities;
validator protection is confined to intended instances and idempotent.
Synthetic fixtures only. No actual PII or external network interactions.
"""

import logging

import pytest
from presidio_analyzer import PatternRecognizer

from privacy_proxy.l3.registry import PRODUCER_TYPES
from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.l3.timeout_guard import (
    L3DependencyTimeoutError,
    TimeoutCallable,
    protect_number_validators,
)
from tests import fixtures

CASES = [
    ("KR_RRN", "RRN_VALID"),
    ("KR_FRN", "FRN_VALID"),
    ("KR_BRN", "BRN_VALID"),
    ("KR_DRIVER_LICENSE", "LICENSE_VALID"),
]
MARKER = "SYNTHETIC_CROSS_ENTITY_VALIDATOR_TIMEOUT_PRIVATE_MARKER"


@pytest.mark.parametrize("entity, fixture_name", CASES)
def test_prior_real_passport_detection_does_not_escape_validator_timeout(
    entity, fixture_name, monkeypatch, caplog
):
    # Patch the real producer method BEFORE service construction so the actual
    # per-instance TimeoutCallable captures the injected fault.
    cls = PRODUCER_TYPES[entity]
    state = {"fault_reached": False, "passport_emitted": False}

    def faulting_validate(self, value):
        state["fault_reached"] = True
        raise TimeoutError(MARKER)

    monkeypatch.setattr(cls, "validate_result", faulting_validate)
    service = L3AnalyzerService()
    registry = service._analyzer.registry
    passport = next(p for p in registry.recognizers if p.supported_entities == ["KR_PASSPORT"])
    # The test must establish that a real passport result was produced first.
    # Test-only execution-order control: AnalyzerEngine iterates the result
    # of registry.get_recognizers(), not necessarily registry.recognizers.
    # Keep both actual producers and actual analyze implementations intact.
    original_get_recognizers = registry.get_recognizers

    def passport_first(*args, **kwargs):
        selected = list(original_get_recognizers(*args, **kwargs))
        if passport in selected:
            selected.remove(passport)
            selected.insert(0, passport)
        state["passport_selected_first"] = bool(selected) and selected[0] is passport
        return selected

    monkeypatch.setattr(registry, "get_recognizers", passport_first)
    analyze_passport = passport.analyze

    def spy_real_passport(*args, **kwargs):
        result = analyze_passport(*args, **kwargs)
        state["passport_emitted"] = any(item.entity_type == "KR_PASSPORT" for item in result)
        return result

    monkeypatch.setattr(passport, "analyze", spy_real_passport)
    text = fixtures.PASSPORT + " | " + getattr(fixtures, fixture_name)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(L3DependencyTimeoutError, match="L3_DEPENDENCY_TIMEOUT") as exc,
    ):
        service.analyze(text, "synthetic", entities=["KR_PASSPORT", entity])

    assert state["passport_emitted"], "Harness did not establish prior real passport match"
    assert state["fault_reached"], "Harness did not reach validator fault"
    assert MARKER not in str(exc.value)
    assert MARKER not in caplog.text


def test_number_validator_protection_is_instance_local_and_idempotent():
    service_a = L3AnalyzerService()
    service_b = L3AnalyzerService()
    producers_a = {p.supported_entities[0]: p for p in service_a._analyzer.registry.recognizers}
    producers_b = {p.supported_entities[0]: p for p in service_b._analyzer.registry.recognizers}
    targets = {item[0] for item in CASES}
    before = {
        name: producer.validate_result
        for name, producer in producers_a.items()
        if isinstance(producer, PatternRecognizer)
    }

    assert targets <= set(before)
    for name in targets:
        assert isinstance(before[name], TimeoutCallable)
        assert before[name].callback.__self__ is producers_a[name]
        other = producers_b[name].validate_result
        assert isinstance(other, TimeoutCallable)
        assert other is not before[name]
        assert other.callback.__self__ is producers_b[name]

    # Non-target recognizers may already have TimeoutCallable from other guards.
    # The loop below checks unchanged callable identity for every recognizer.

    protect_number_validators(service_a._analyzer.registry)
    protect_number_validators(service_a._analyzer.registry)
    for name, original_callable in before.items():
        current_callable = producers_a[name].validate_result

        if isinstance(original_callable, TimeoutCallable):
            assert current_callable is original_callable
        else:
            assert not isinstance(current_callable, TimeoutCallable)
            assert current_callable.__self__ is original_callable.__self__
            assert current_callable.__func__ is original_callable.__func__
