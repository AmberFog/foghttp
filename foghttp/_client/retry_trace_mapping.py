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
    raw_attempts = raw.attempts
    attempts = tuple(
        _retry_attempt_from_raw(
            attempt,
            terminal_error_type=_terminal_error_type(
                outcome=outcome,
                attempt_index=attempt_index,
                attempt_count=len(raw_attempts),
                error_type=error_type,
            ),
        )
        for attempt_index, attempt in enumerate(raw_attempts)
    )
    return RetryTrace(
        attempts=attempts,
        outcome=outcome,
        status_code=raw.status_code,
        error_type=error_type if outcome == RetryTraceOutcome.ERROR else None,
        elapsed=raw.elapsed,
    )


def _terminal_error_type(
    *,
    outcome: RetryTraceOutcome,
    attempt_index: int,
    attempt_count: int,
    error_type: str | None,
) -> str | None:
    if outcome != RetryTraceOutcome.ERROR or attempt_index + 1 != attempt_count:
        return None
    return error_type


def _retry_attempt_from_raw(
    raw: "_foghttp.RawRetryAttempt",
    *,
    terminal_error_type: str | None,
) -> RetryAttempt:
    error_type = raw.error_type
    if error_type is None and raw.status_code is None:
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
        elapsed=raw.elapsed,
    )
