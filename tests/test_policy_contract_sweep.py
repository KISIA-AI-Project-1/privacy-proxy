"""계약표(e2e_leak_test.py)가 실제 L5/L6 구현과 어긋나지 않는지 전수 대조한다.

``e2e_leak_test.allowed_outcomes``는 src와 독립적으로 쓴 표다. 독립적이라는 것은 같은 실수를
공유하지 않는다는 장점이면서, 구현이 바뀌어도 표가 따라가지 않는다는 위험이기도 하다.
이 테스트는 지원하는 모든 엔티티 유형에 대해 "L5가 낼 수 있는 계획"과 "L6가 그 계획에 실제로
하는 처리"를 구하고 표와 **정확히 같은지**(더 느슨하거나 더 엄격하지 않은지) 확인한다.
"""

import pytest
from e2e_leak_test import ALWAYS_TOKENIZED, CONTRACT_EXCEPTIONS, allowed_outcomes

from privacy_proxy.risk.entity_contract import L5_SUPPORTED_ENTITY_TYPES
from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class
from privacy_proxy.risk.score import _entity_policies
from privacy_proxy.schemas import DetectedPII, DetectionTier
from privacy_proxy.vault.tokenizer import Strategy, resolve_spec


def l5_possible_plans(entity_type: str) -> tuple[PrivacyClass, set[str]]:
    """실제 risk/score.py::_entity_policies를 저/중/고 점수로 호출해 낼 수 있는 계획을 모은다."""
    sample = DetectedPII(
        segment_id="seg-1",
        start_idx=0,
        end_idx=1,
        entity_type=entity_type,
        original_value="x",
        normalized="x",
        confidence=None,
        tier=DetectionTier.DETERMINISTIC,
        source="sweep",
    )
    kind = privacy_class(sample)
    plans = {
        _entity_policies([(sample, kind)], qi_score)[0].action for qi_score in (0.0, 45.0, 90.0)
    }
    return kind, plans


def l6_actual_action(entity_type: str, plan: str) -> str:
    spec = resolve_spec(entity_type, plan)
    if spec is None:
        return "KEEP"
    return "GENERALIZE" if spec.strategy is Strategy.GENERALIZE else "TOKENIZE"


CASES = [
    (entity_type, plan)
    for entity_type in sorted(L5_SUPPORTED_ENTITY_TYPES)
    for plan in sorted(l5_possible_plans(entity_type)[1])
]


@pytest.mark.parametrize(("entity_type", "plan"), CASES)
def test_contract_matches_real_l5_plan_and_l6_action(entity_type, plan):
    actual = l6_actual_action(entity_type, plan)
    assert allowed_outcomes(entity_type, plan) == frozenset({actual}), (
        f"{entity_type}: L5 plan {plan} -> L6 {actual}, "
        f"contract says {allowed_outcomes(entity_type, plan)}"
    )


def test_sweep_covers_every_supported_type_with_at_least_one_plan():
    assert {entity_type for entity_type, _ in CASES} == set(L5_SUPPORTED_ENTITY_TYPES)


def test_always_tokenized_types_are_planned_tokenize_by_l5():
    for entity_type in ALWAYS_TOKENIZED:
        assert l5_possible_plans(entity_type)[1] == {"TOKENIZE"}, entity_type


def test_every_contract_exception_is_reachable_from_l5():
    """도달할 수 없는 예외는 쓸모없는 구멍이다. 표에 남기지 않는다."""
    reachable = {(entity_type, plan) for entity_type, plan in CASES}
    assert set(CONTRACT_EXCEPTIONS) <= reachable
