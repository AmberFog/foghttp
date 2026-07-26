from collections.abc import Sequence

from foghttp.methods import GET
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from foghttp.telemetry import (
    TelemetryEvent,
    TelemetryEventType,
    TelemetryRequestMode,
    TelemetryRequestOutcome,
)
from tests.client_telemetry.constants import LOWER_LEVEL_EVENT_TYPES


def assert_event_types(
    events: Sequence[TelemetryEvent],
    expected: tuple[TelemetryEventType, ...],
) -> None:
    actual = tuple(event.event_type for event in events if event.event_type not in LOWER_LEVEL_EVENT_TYPES)
    if actual != expected:
        raise AssertionError(actual)


def assert_event_sequence_is_monotonic(events: Sequence[TelemetryEvent]) -> None:
    actual = tuple(event.event_sequence for event in events)
    expected = tuple(range(1, len(events) + 1))
    if actual != expected:
        raise AssertionError(actual)


def assert_event_sequences_are_unique(events: Sequence[TelemetryEvent]) -> None:
    actual = sorted(event.event_sequence for event in events)
    expected = list(range(1, len(events) + 1))
    if actual != expected:
        raise AssertionError(actual)


def assert_single_request_id(events: Sequence[TelemetryEvent]) -> None:
    request_ids = {event.request_id for event in events if event.request_id is not None}
    client_scoped_types = {event.event_type for event in events if event.request_id is None}
    allowed_client_scoped_types = {
        TelemetryEventType.CONNECTION_OPENED,
        TelemetryEventType.CONNECTION_OPEN_FAILED,
        TelemetryEventType.CONNECTION_CLOSED,
    }
    if len(request_ids) != 1 or client_scoped_types - allowed_client_scoped_types:
        raise AssertionError(request_ids)


def assert_redacted_urls_do_not_contain(events: Sequence[TelemetryEvent], secret: str) -> None:
    leaked_urls = tuple(event.redacted_url for event in events if event.redacted_url and secret in event.redacted_url)
    if leaked_urls:
        raise AssertionError(leaked_urls)


def assert_stream_completion(
    events: Sequence[TelemetryEvent],
    *,
    outcome: TelemetryRequestOutcome,
    error_type: str | None = None,
) -> None:
    body_event = _event(events, TelemetryEventType.RESPONSE_BODY_FINISHED)
    request_event = _event(events, TelemetryEventType.REQUEST_FINISHED)
    actual_values = {
        "body_header_elapsed_ns": body_event.elapsed_ns,
        "body_request_elapsed_ns": body_event.request_elapsed_ns,
        "body_outcome": body_event.outcome,
        "body_error_type": body_event.error_type,
        "request_header_elapsed_ns": request_event.elapsed_ns,
        "request_body_elapsed_ns": request_event.body_elapsed_ns,
        "request_outcome": request_event.outcome,
        "request_error_type": request_event.error_type,
    }
    expected_values = {
        "body_header_elapsed_ns": None,
        "body_request_elapsed_ns": None,
        "body_outcome": outcome,
        "body_error_type": error_type,
        "request_header_elapsed_ns": None,
        "request_body_elapsed_ns": None,
        "request_outcome": outcome,
        "request_error_type": error_type,
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)
    body_elapsed_ns = body_event.body_elapsed_ns
    request_elapsed_ns = request_event.request_elapsed_ns
    if body_elapsed_ns is None or body_elapsed_ns < 0:
        raise AssertionError(body_elapsed_ns)
    if request_elapsed_ns is None or request_elapsed_ns < body_elapsed_ns:
        raise AssertionError((request_elapsed_ns, body_elapsed_ns))


def assert_stream_request_failure(
    events: Sequence[TelemetryEvent],
    *,
    error_type: str,
) -> None:
    body_events = tuple(event for event in events if event.event_type is TelemetryEventType.RESPONSE_BODY_FINISHED)
    if body_events:
        raise AssertionError(body_events)
    request_event = _event(events, TelemetryEventType.REQUEST_FINISHED)
    actual_values = {
        "mode": request_event.mode,
        "elapsed_ns": request_event.elapsed_ns,
        "body_elapsed_ns": request_event.body_elapsed_ns,
        "outcome": request_event.outcome,
        "error_type": request_event.error_type,
    }
    expected_values = {
        "mode": TelemetryRequestMode.STREAM,
        "elapsed_ns": None,
        "body_elapsed_ns": None,
        "outcome": TelemetryRequestOutcome.ERROR,
        "error_type": error_type,
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)
    if request_event.request_elapsed_ns is None or request_event.request_elapsed_ns < 0:
        raise AssertionError(request_event.request_elapsed_ns)


def assert_connection_abort(
    events: Sequence[TelemetryEvent],
    *,
    outcome: TelemetryRequestOutcome,
    error_type: str | None,
) -> None:
    event = _event(events, TelemetryEventType.CONNECTION_ABORTED)
    actual = (event.outcome, event.error_type)
    expected = (outcome, error_type)
    if actual != expected:
        raise AssertionError(actual)


def assert_buffered_redirect_contract(events: Sequence[TelemetryEvent]) -> None:
    start_event = _event(events, TelemetryEventType.REQUEST_STARTED)
    redirect_event = _event(events, TelemetryEventType.REDIRECT_DECISION)
    body_event = _event(events, TelemetryEventType.RESPONSE_BODY_FINISHED)
    finish_event = _event(events, TelemetryEventType.REQUEST_FINISHED)

    expected_values = {
        "start_mode": TelemetryRequestMode.BUFFERED,
        "start_method": GET,
        "redirect_type": TelemetryEventType.REDIRECT_DECISION,
        "redirect_hop": 1,
        "redirect_status": FOUND,
        "finish_status": OK,
        "finish_outcome": TelemetryRequestOutcome.SUCCESS,
    }
    actual_values = {
        "start_mode": start_event.mode,
        "start_method": start_event.method,
        "redirect_type": redirect_event.event_type,
        "redirect_hop": redirect_event.redirect_hop,
        "redirect_status": redirect_event.status_code,
        "finish_status": finish_event.status_code,
        "finish_outcome": finish_event.outcome,
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)
    duration_values = (
        body_event.body_elapsed_ns,
        body_event.request_elapsed_ns,
        finish_event.body_elapsed_ns,
        finish_event.request_elapsed_ns,
    )
    if duration_values != (None, None, None, None):
        raise AssertionError(duration_values)
    if "token=<redacted>" not in (start_event.redacted_url or ""):
        raise AssertionError(start_event.redacted_url)


def _event(
    events: Sequence[TelemetryEvent],
    event_type: TelemetryEventType,
) -> TelemetryEvent:
    matches = tuple(event for event in events if event.event_type == event_type)
    if len(matches) != 1:
        raise AssertionError((event_type, len(matches)))
    return matches[0]
