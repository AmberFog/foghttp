__all__ = ("retry_events", "single_retry_event")

from collections.abc import Sequence

import foghttp


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
