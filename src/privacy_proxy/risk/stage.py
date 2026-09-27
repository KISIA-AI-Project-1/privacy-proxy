"""Fail-closed async boundary for the L5 pipeline stage."""

from privacy_proxy.risk.score import assess_risk
from privacy_proxy.schemas import ProxyContext


async def run_l5_risk_scoring(context: ProxyContext) -> ProxyContext:
    """Run the real L5 evaluator using the integration pipeline's async shape.

    The L1-L9 orchestrator advances only while ``context.status == "success"``.
    Converting every L5 failure to a generic failed state therefore prevents L6
    and L7 from running.  Error text intentionally excludes detected values and
    raw prompt fragments.
    """
    if context.status != "success":
        return context

    try:
        return assess_risk(context)
    except ValueError:
        context.status = "failed"
        context.error = "L5_VALIDATION_FAILED"
    except Exception:  # pragma: no cover - last-resort pipeline safety boundary
        context.status = "failed"
        context.error = "L5_RISK_ASSESSMENT_FAILED"
    return context
