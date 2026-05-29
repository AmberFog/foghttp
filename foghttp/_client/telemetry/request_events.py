__all__ = ("emit_request_error_telemetry", "start_request_telemetry")

import asyncio

from ...telemetry import TelemetryRequestOutcome
from .emission import TelemetryCompletion
from .request_context import TelemetryRequestContext


def start_request_telemetry(telemetry_context: TelemetryRequestContext | None) -> bool:
    if telemetry_context is None:
        return False
    telemetry_context.request_started()
    return True


def emit_request_error_telemetry(
    telemetry_context: TelemetryRequestContext | None,
    *,
    telemetry_started: bool,
    error: BaseException,
) -> None:
    if telemetry_context is None or not telemetry_started:
        return
    telemetry_context.request_finished(
        TelemetryCompletion(
            response=None,
            outcome=_request_error_outcome(error),
            error=error,
            suppress_hook_errors=True,
        ),
    )


def _request_error_outcome(error: BaseException) -> TelemetryRequestOutcome:
    if isinstance(error, asyncio.CancelledError):
        return TelemetryRequestOutcome.CANCELLED
    return TelemetryRequestOutcome.ERROR
