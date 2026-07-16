__all__ = ("emit_retry_decisions",)

from collections.abc import Sequence

from ..retry import RetryDecisionData
from .request_context import TelemetryRequestContext


def emit_retry_decisions(
    telemetry_context: TelemetryRequestContext,
    decisions: Sequence[RetryDecisionData],
    *,
    suppress_hook_errors: bool,
) -> None:
    for decision in decisions:
        telemetry_context.retry_decision(
            decision,
            suppress_hook_errors=suppress_hook_errors,
        )
