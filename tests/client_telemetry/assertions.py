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


def assert_event_types(
    events: Sequence[TelemetryEvent],
    expected: tuple[TelemetryEventType, ...],
) -> None:
    actual = tuple(event.event_type for event in events)
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
    request_ids = {event.request_id for event in events}
    if len(request_ids) != 1 or None in request_ids:
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
    body_event = events[-2]
    request_event = events[-1]
    actual_values = {
        "body_elapsed_ns": body_event.elapsed_ns,
        "body_outcome": body_event.outcome,
        "body_error_type": body_event.error_type,
        "request_elapsed_ns": request_event.elapsed_ns,
        "request_outcome": request_event.outcome,
        "request_error_type": request_event.error_type,
    }
    expected_values = {
        "body_elapsed_ns": None,
        "body_outcome": outcome,
        "body_error_type": error_type,
        "request_elapsed_ns": None,
        "request_outcome": outcome,
        "request_error_type": error_type,
    }
    if actual_values != expected_values:
        raise AssertionError(actual_values)


def assert_buffered_redirect_contract(events: Sequence[TelemetryEvent]) -> None:
    start_event = events[0]
    redirect_event = events[1]
    finish_event = events[-1]

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
    if "token=<redacted>" not in (start_event.redacted_url or ""):
        raise AssertionError(start_event.redacted_url)
