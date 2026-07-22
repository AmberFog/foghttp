__all__ = ("raw_retry_trace_on_error", "retry_trace_from_raw")

from typing import Protocol

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..retry_trace import RetryAttempt, RetryTrace, RetryTraceOutcome
from ..telemetry import TelemetryRetryDecision, TelemetryRetryReason


_RETRY_TRACE_ATTRIBUTE = "_foghttp_retry_trace"


class RawRetryTraceSource(Protocol):
    @property
    def retry_trace(self) -> "_foghttp.RawRetryTrace | None": ...


def retry_trace_from_raw(source: RawRetryTraceSource) -> RetryTrace | None:
    raw_trace = source.retry_trace
    if raw_trace is None:
        return None
    return _retry_trace_from_raw(raw_trace, error_type=None)


def raw_retry_trace_on_error(error: object, *, error_type: str) -> RetryTrace | None:
    raw_trace = getattr(error, _RETRY_TRACE_ATTRIBUTE, None)
    if not isinstance(raw_trace, _foghttp.RawRetryTrace):
        return None
    return _retry_trace_from_raw(raw_trace, error_type=error_type)


def _retry_trace_from_raw(
    raw: "_foghttp.RawRetryTrace",
    *,
    error_type: str | None,
) -> RetryTrace:
    outcome = RetryTraceOutcome(raw.outcome)
    terminal_error_type = (
        error_type if outcome == RetryTraceOutcome.ERROR and raw.terminal_error_on_last_attempt else None
    )
    return RetryTrace(
        attempts=_retry_attempts_from_raw(
            raw.attempts,
            terminal_error_type=terminal_error_type,
        ),
        outcome=outcome,
        status_code=raw.status_code,
        error_type=error_type if outcome == RetryTraceOutcome.ERROR else None,
        elapsed=raw.elapsed,
    )


def _retry_attempts_from_raw(
    raw_attempts: list["_foghttp.RawRetryAttempt"],
    *,
    terminal_error_type: str | None,
) -> tuple[RetryAttempt, ...]:
    terminal_index = len(raw_attempts) - 1
    return tuple(
        _retry_attempt_from_raw(
            attempt,
            terminal_error_type=(terminal_error_type if attempt_index == terminal_index else None),
        )
        for attempt_index, attempt in enumerate(raw_attempts)
    )


def _retry_attempt_from_raw(
    raw: "_foghttp.RawRetryAttempt",
    *,
    terminal_error_type: str | None,
) -> RetryAttempt:
    error_type = raw.error_type
    if terminal_error_type is not None:
        error_type = terminal_error_type
    return RetryAttempt(
        attempt=raw.attempt,
        method=raw.method,
        origin=raw.origin,
        redirect_hop=raw.redirect_hop,
        status_code=raw.status_code,
        error_type=error_type,
        decision=None if raw.decision is None else TelemetryRetryDecision(raw.decision),
        reason=None if raw.reason is None else TelemetryRetryReason(raw.reason),
        backoff=raw.backoff,
        decision_elapsed=raw.decision_elapsed,
        completed_elapsed=raw.completed_elapsed,
    )
