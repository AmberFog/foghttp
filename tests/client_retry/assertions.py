__all__ = ("require_retry_trace", "retry_events", "single_retry_event")

from collections.abc import Sequence
from typing import Protocol

import foghttp


_MISSING_RETRY_TRACE = "expected retry trace"


class RetryTraceSource(Protocol):
    @property
    def retry_trace(self) -> foghttp.RetryTrace | None: ...


def require_retry_trace(source: RetryTraceSource) -> foghttp.RetryTrace:
    trace = source.retry_trace
    if trace is None:
        raise AssertionError(_MISSING_RETRY_TRACE)
    return trace


def retry_events(
    events: Sequence[foghttp.TelemetryEvent],
) -> tuple[foghttp.TelemetryEvent, ...]:
    return tuple(event for event in events if event.event_type == foghttp.TelemetryEventType.RETRY_DECISION)


def single_retry_event(
    events: Sequence[foghttp.TelemetryEvent],
) -> foghttp.TelemetryEvent:
    matching = retry_events(events)
    if len(matching) != 1:
        raise AssertionError(matching)
    return matching[0]
