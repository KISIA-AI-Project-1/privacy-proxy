"""Risk score, level, and L6 policy selection for pipeline layer L5."""

from time import perf_counter

from privacy_proxy.risk.combination import combination_score, select_representative_qis
from privacy_proxy.risk.entity_contract import L5_SUPPORTED_ENTITY_TYPES
from privacy_proxy.risk.quasi_identifiers import PrivacyClass, privacy_class
from privacy_proxy.risk.resolver import resolve_overlaps
from privacy_proxy.schemas import ProxyContext

LOW_MAX = 30.0
MEDIUM_MAX = 60.0
DIRECT_IDENTIFIER_FLOOR = 80.0
SERVICE_IDENTIFIER_FLOOR = 85.0
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
    unsupported_types = sorted(
        {
            str(entity.entity_type)
            for entity in context.detected_entities
            if str(entity.entity_type) not in L5_SUPPORTED_ENTITY_TYPES
        }
    )
    if unsupported_types:
        raise ValueError("unsupported detected entity type")

    context.detected_entities = resolve_overlaps(context.detected_entities)
    classes = [(entity, privacy_class(entity)) for entity in context.detected_entities]

    features = select_representative_qis(context.detected_entities)
    reasons = [feature.reason for feature in features]
    score = sum(feature.base_score for feature in features)
    bonus, combination_reasons = combination_score(features)
    score += bonus
    reasons.extend(combination_reasons)

    direct = [entity for entity, kind in classes if kind is PrivacyClass.DIRECT]
    service = [entity for entity, kind in classes if kind is PrivacyClass.SERVICE]
    sensitive = [entity for entity, kind in classes if kind is PrivacyClass.SENSITIVE]

    if direct:
        score = max(score, DIRECT_IDENTIFIER_FLOOR)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in direct}))
        _append_once(reasons, f"직접식별자({kinds})가 포함되어 우선 보호가 필요함")
    if service:
        score = max(score, SERVICE_IDENTIFIER_FLOOR)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in service}))
        _append_once(reasons, f"서비스 식별자({kinds})가 포함되어 우선 보호가 필요함")
    if sensitive:
        confidences = [entity.confidence for entity in sensitive]
        if any(value is None for value in confidences):
            sensitive_score = SENSITIVE_INFORMATION_MAX_SCORE
            detail = "confidence 미산정: 정책상 보수적 대체 점수 80 적용"
        else:
            max_confidence = max(value for value in confidences if value is not None)
            sensitive_score = SENSITIVE_INFORMATION_MAX_SCORE * max_confidence
            detail = f"confidence={max_confidence:.2f}"
        score = max(score, sensitive_score)
        kinds = ", ".join(sorted({entity.entity_type.upper() for entity in sensitive}))
        _append_once(reasons, f"민감정보 후보({kinds}, {detail})가 포함됨")

    final_score = min(100.0, round(score, 2))
    level = _level(final_score)
    if direct or service or sensitive:
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
