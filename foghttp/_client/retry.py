__all__ = (
    "bind_error_retry_trace",
    "bind_retry_trace",
    "public_retry_decisions",
    "public_retry_trace",
)

from typing import TypeVar

from ..errors import FogHTTPError
from ..retry_trace import RetryAttempt, RetryTrace
from .retry_trace_mapping import raw_retry_trace_on_error


_PUBLIC_RETRY_TRACE_ATTRIBUTE = "_retry_trace"
_TargetT = TypeVar("_TargetT")


def bind_retry_trace(target: _TargetT, trace: RetryTrace | None) -> _TargetT:
    if trace is not None:
        object.__setattr__(target, _PUBLIC_RETRY_TRACE_ATTRIBUTE, trace)
    return target


def bind_error_retry_trace(error: BaseException) -> None:
    if isinstance(error, FogHTTPError):
        bind_retry_trace(error, public_retry_trace(error))


def public_retry_trace(source: object) -> RetryTrace | None:
    trace = getattr(source, _PUBLIC_RETRY_TRACE_ATTRIBUTE, None)
    if isinstance(trace, RetryTrace):
        return trace
    return raw_retry_trace_on_error(source, error_type=type(source).__name__)


def public_retry_decisions(source: object) -> tuple[RetryAttempt, ...]:
    trace = public_retry_trace(source)
    if trace is None:
        return ()
    return tuple(filter(_has_retry_decision, trace.attempts))


def _has_retry_decision(attempt: RetryAttempt) -> bool:
    return attempt.decision is not None and attempt.reason is not None
