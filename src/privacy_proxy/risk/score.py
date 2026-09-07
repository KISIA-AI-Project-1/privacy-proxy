"""Risk score, level, and L6 policy selection for pipeline layer L5."""

from time import perf_counter

from privacy_proxy.models import ProxyContext

from privacy_proxy.risk.combination import combination_score, select_representative_qis
from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class

LOW_MAX = 30.0
MEDIUM_MAX = 60.0
DIRECT_IDENTIFIER_FLOOR = 80.0
UNIQUE_IDENTIFIER_FLOOR = 85.0
SENSITIVE_INFORMATION_MAX_SCORE = 80.0


def _level(score: float) -> str:
    if score < LOW_MAX:
        return "LOW"
    if score < MEDIUM_MAX:
        return "MEDIUM"
    return "HIGH"


def _append_once(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def assess_risk(context: ProxyContext) -> ProxyContext:
    """Evaluate L5 risk in place without masking or changing the raw prompt."""
    started = perf_counter()
    context.validate_detected_spans()

    features = select_representative_qis(context.detected_entities)
    reasons = [feature.reason for feature in features]
    score = sum(feature.base_score for feature in features)
    bonus, combination_reasons = combination_score(features)
    score += bonus
    reasons.extend(combination_reasons)

    classes = [(entity, privacy_class(entity)) for entity in context.detected_entities]
    direct = [entity for entity, kind in classes if kind is PrivacyClass.DIRECT]
    unique = [entity for entity, kind in classes if kind is PrivacyClass.UNIQUE]
    sensitive = [entity for entity, kind in classes if kind is PrivacyClass.SENSITIVE]

    if direct:
        score = max(score, DIRECT_IDENTIFIER_FLOOR)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in direct}))
        _append_once(reasons, f"직접식별자({kinds})가 포함되어 우선 보호가 필요함")
    if unique:
        score = max(score, UNIQUE_IDENTIFIER_FLOOR)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in unique}))
        _append_once(reasons, f"서비스 식별자({kinds})가 포함되어 우선 보호가 필요함")
    if sensitive:
        max_confidence = max(entity.confidence for entity in sensitive)
        sensitive_score = SENSITIVE_INFORMATION_MAX_SCORE * max_confidence
        score = max(score, sensitive_score)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in sensitive}))
        _append_once(
            reasons,
            f"민감정보 후보({kinds}, confidence={max_confidence:.2f})가 포함됨",
        )

    final_score = min(100.0, round(score, 2))
    level = _level(final_score)
    if direct or unique or sensitive:
        action = "TOKENIZE"
    elif level in {"MEDIUM", "HIGH"}:
        action = "GENERALIZE"
    else:
        action = "ALLOW"

    context.risk_score = final_score
    context.risk_level = level
    context.risk_reasons = list(dict.fromkeys(reasons))
    context.policy_action = action
    context.latency_ms["L5"] = round((perf_counter() - started) * 1000, 3)
    return context
