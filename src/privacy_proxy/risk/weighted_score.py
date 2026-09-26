"""Experimental three-component L5 score.

This module is deliberately separate from ``score.assess_risk`` until the team
calibrates the proposed weights and thresholds with fixtures.  It consumes only
the canonical entity contract and therefore fails closed for unknown types.
"""

from dataclasses import dataclass
from math import prod

from privacy_proxy.risk.combination import select_representative_qis
from privacy_proxy.risk.entity_contract import L5_SUPPORTED_ENTITY_TYPES
from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class
from privacy_proxy.schemas import DetectedPII, DetectionTier

IDENTIFIABILITY_WEIGHT = 0.35
SENSITIVITY_WEIGHT = 0.45
COMBINATION_WEIGHT = 0.20

_IDENTIFIABILITY_BASE = {
    PrivacyClass.DIRECT: 1.0,
    PrivacyClass.SERVICE: 0.90,
    PrivacyClass.SENSITIVE: 0.05,
}

# Operational harm weights, not statutory declarations that every listed type
# is legally "sensitive information".  The four SENSITIVE_* types remain the
# only members of the project's SENSITIVE_INFORMATION class.
_SENSITIVITY_BY_TYPE = {
    "SENSITIVE_HEALTH": 1.00,
    "SENSITIVE_RELIGION": 0.90,
    "SENSITIVE_FINANCIAL": 0.90,
    "SENSITIVE_FAMILY": 0.70,
    "ACCOUNT_NUMBER": 0.85,
    "RRN": 0.80,
    "ADDRESS_ROAD": 0.55,
    "ADDRESS_LOT": 0.55,
    "ADDRESS_DETAIL": 0.55,
    "PHONE": 0.50,
    "EMAIL": 0.50,
    "CUSTOMS_CLEARANCE_ID": 0.50,
    "ORDER_ID": 0.45,
    "TRACKING_NUMBER": 0.45,
    "CUSTOMER_ID": 0.45,
    "BUSINESS_REGISTRATION_NUMBER": 0.20,
    "PERSON_KO": 0.30,
    "LOCATION_INFORMAL": 0.25,
}

_TIER_RELIABILITY = {
    DetectionTier.DETERMINISTIC: 1.00,
    DetectionTier.RULE_ANCHORED: 0.95,
    DetectionTier.MODEL: 0.85,
    DetectionTier.CANDIDATE: 0.50,
}


@dataclass(frozen=True, slots=True)
class WeightedRiskResult:
    """Auditable result of the proposed weighted score."""

    identification: float
    sensitivity: float
    combination: float
    score: float
    qi_category_count: int
    action: str
    reasons: tuple[str, ...]

    @property
    def should_generalize(self) -> bool:
        return self.action == "GENERALIZE"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _combined_probability(values: list[float]) -> float:
    """Combine independent signals without allowing their sum to exceed one."""
    return 1.0 - prod(1.0 - _clamp(value) for value in values)


def _reliability(entity: DetectedPII) -> float:
    if entity.confidence is None:
        raise ValueError("experimental weighted score requires measured confidence")
    return entity.confidence * _TIER_RELIABILITY[entity.tier]


def _identification_component(entities: list[DetectedPII]) -> float:
    signals: list[float] = []
    for entity in entities:
        kind = privacy_class(entity)
        if kind is PrivacyClass.QI:
            features = select_representative_qis([entity])
            if features:
                # Existing QI base scores range from 5 to 22.  Dividing by 40
                # maps them to weak-to-moderate identifying signals.
                signals.append((features[0].base_score / 40.0) * _reliability(entity))
        else:
            signals.append(_IDENTIFIABILITY_BASE.get(kind, 0.0) * _reliability(entity))
    return _clamp(_combined_probability(signals))


def _sensitivity_component(entities: list[DetectedPII]) -> float:
    signals = [
        _SENSITIVITY_BY_TYPE[entity.entity_type.upper()] * _reliability(entity)
        for entity in entities
    ]
    return _clamp(_combined_probability(signals))


def _combination_component(
    entities: list[DetectedPII],
) -> tuple[float, int, list[str]]:
    features = select_representative_qis(entities)
    categories = {feature.category for feature in features}
    count = len(categories)
    component = {0: 0.0, 1: 0.0, 2: 0.35, 3: 0.70}.get(count, 1.0)
    reasons: list[str] = []

    classes = {privacy_class(entity) for entity in entities}
    if PrivacyClass.SENSITIVE in classes and (
        PrivacyClass.DIRECT in classes or PrivacyClass.SERVICE in classes
    ):
        component = max(component, 0.90)
        reasons.append("민감정보와 연결 가능한 식별자가 함께 탐지됨")

    if count >= 3:
        reasons.append(f"독립적인 준식별자 범주 {count}개가 결합됨")
    return component, count, reasons


def calculate_weighted_risk(entities: list[DetectedPII]) -> WeightedRiskResult:
    """Calculate the proposed score and request-level L5 policy.

    Unknown entity names raise ``ValueError``.  Direct, service, and sensitive
    entities are tokenized regardless of the numeric score.  The three-QI rule
    is an explicit policy guard; a high-risk two-QI pair can also generalize via
    the numeric threshold.
    """
    unsupported = sorted(
        {
            str(entity.entity_type)
            for entity in entities
            if str(entity.entity_type) not in L5_SUPPORTED_ENTITY_TYPES
        }
    )
    if unsupported:
        raise ValueError("unsupported detected entity type")

    classified = [(entity, privacy_class(entity)) for entity in entities]
    identification = _identification_component(entities)
    sensitivity = _sensitivity_component(entities)
    combination, qi_count, reasons = _combination_component(entities)
    score = round(
        100.0
        * (
            IDENTIFIABILITY_WEIGHT * identification
            + SENSITIVITY_WEIGHT * sensitivity
            + COMBINATION_WEIGHT * combination
        ),
        2,
    )

    kinds = {kind for _, kind in classified}
    if kinds & {PrivacyClass.DIRECT, PrivacyClass.SERVICE, PrivacyClass.SENSITIVE}:
        action = "TOKENIZE"
        reasons.append("직접·서비스 식별자 또는 민감정보는 점수와 무관하게 토큰화함")
    elif qi_count >= 3 or score >= 30.0:
        action = "GENERALIZE"
        reasons.append("QI 결합 규칙 또는 위험 점수 임계값을 충족함")
    else:
        action = "ALLOW"

    return WeightedRiskResult(
        identification=round(identification, 4),
        sensitivity=round(sensitivity, 4),
        combination=round(combination, 4),
        score=score,
        qi_category_count=qi_count,
        action=action,
        reasons=tuple(dict.fromkeys(reasons)),
    )
