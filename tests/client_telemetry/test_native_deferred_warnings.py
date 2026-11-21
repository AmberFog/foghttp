from typing import TYPE_CHECKING, Literal, cast
import warnings

import pytest

import foghttp
from foghttp._client.telemetry import TelemetryDispatcher
from foghttp.telemetry.config import TelemetryHookErrorPolicy

from .native_warning_sources import (
    NativeWarningBatch,
    NativeWarningRecord,
    NativeWarningSink,
    capture_promoted_warnings,
    raise_ambient_failure,
)


if TYPE_CHECKING:
    from foghttp._foghttp import RawClient


def test_suppressed_request_defers_original_client_warning_and_delivers_whole_batch() -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"))
    batch = NativeWarningBatch(
        [
            NativeWarningRecord("connection_closed"),
            NativeWarningRecord("connection_aborted", request_id=7),
            NativeWarningRecord("connection_closed"),
            NativeWarningRecord("connection_reused", request_id=7),
            NativeWarningRecord("connection_reused", request_id=8),
        ],
    )

    with capture_promoted_warnings() as captured, warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=7, suppress_hook_errors=True)

    assert len(captured) == 1
    original_warning = captured[0]
    assert original_warning.__context__ is sink.failures[0]
    assert original_warning.__cause__ is None
    expected_events = [
        ("connection_closed", None),
        ("connection_aborted", 7),
        ("connection_closed", None),
        ("connection_reused", 7),
    ]
    assert [(event.event_type.value, event.request_id) for event in sink.events] == expected_events
    assert [record.request_id for record in batch.records] == [8]

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=8, suppress_hook_errors=False)
        batch.records.extend([NativeWarningRecord("connection_closed"), NativeWarningRecord("connection_closed")])
        try:
            raise_ambient_failure()
        except LookupError:
            with pytest.raises(RuntimeWarning) as replay:
                dispatcher.emit_native_events(
                    cast("RawClient", batch),
                    request_id=None,
                    suppress_hook_errors=False,
                )
    assert replay.value is original_warning
    assert replay.value.__cause__ is sink.failures[0]
    assert batch.records == []
    assert [(event.event_type.value, event.request_id) for event in sink.events] == [
        *expected_events,
        ("connection_reused", 8),
        ("connection_closed", None),
        ("connection_closed", None),
    ]
    dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    assert batch.drains == [7, 8, None]


@pytest.mark.parametrize("action", ["always", "ignore"])
def test_deferred_warning_replay_uses_current_client_close_filter(action: Literal["always", "ignore"]) -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"))
    batch = NativeWarningBatch([NativeWarningRecord("connection_closed")])
    with capture_promoted_warnings() as captured, warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=7, suppress_hook_errors=True)

    with warnings.catch_warnings(record=True) as replayed:
        warnings.simplefilter(action, RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    assert len(sink.events) == 1
    assert batch.drains == [7, None]
    if action == "always":
        assert len(replayed) == 1
        assert replayed[0].message is captured[0]
    else:
        assert replayed == []


def test_warning_replay_preserves_an_existing_explicit_cause() -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"))
    batch = NativeWarningBatch([NativeWarningRecord("connection_closed")])
    with capture_promoted_warnings() as captured, warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=7, suppress_hook_errors=True)
    original_warning = captured[0]
    explicit_cause = ValueError("explicit warning cause")
    original_warning.__cause__ = explicit_cause
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        try:
            raise_ambient_failure()
        except LookupError:
            with pytest.raises(RuntimeWarning) as replay:
                dispatcher.emit_native_events(
                    cast("RawClient", batch),
                    request_id=None,
                    suppress_hook_errors=False,
                )
    assert replay.value is original_warning
    assert replay.value.__cause__ is explicit_cause


@pytest.mark.parametrize("policy", ["raise", "ignore"])
def test_client_failure_keeps_owner_and_policy_during_suppressed_request(policy: TelemetryHookErrorPolicy) -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error=policy))
    batch = NativeWarningBatch([NativeWarningRecord("connection_closed"), NativeWarningRecord("connection_closed")])
    dispatcher.emit_native_events(cast("RawClient", batch), request_id=7, suppress_hook_errors=True)

    if policy == "raise":
        with pytest.raises(foghttp.TelemetryHookError) as deferred:
            dispatcher.emit_native_events(
                cast("RawClient", batch),
                request_id=None,
                suppress_hook_errors=False,
            )
        assert deferred.value.__cause__ is sink.failures[0]
    else:
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    assert [event.event_type for event in sink.events] == [
        foghttp.TelemetryEventType.CONNECTION_CLOSED,
        foghttp.TelemetryEventType.CONNECTION_CLOSED,
    ]
    assert batch.drains == [7, None]


def test_unsuppressed_request_keeps_promoted_warning_at_original_boundary() -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"))
    batch = NativeWarningBatch([NativeWarningRecord("connection_closed")])
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with pytest.raises(RuntimeWarning, match="telemetry event sink failed"):
            dispatcher.emit_native_events(cast("RawClient", batch), request_id=7, suppress_hook_errors=False)
    with warnings.catch_warnings(record=True) as replayed:
        warnings.simplefilter("always", RuntimeWarning)
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    assert replayed == []
    assert len(sink.events) == 1


@pytest.mark.parametrize("suppress_request", [False, True])
def test_ordinary_client_warning_is_emitted_once_without_deferral(*, suppress_request: bool) -> None:
    sink = NativeWarningSink()
    dispatcher = TelemetryDispatcher(foghttp.TelemetryConfig(sink=sink, on_hook_error="warn"))
    batch = NativeWarningBatch([NativeWarningRecord("connection_closed")])
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always", RuntimeWarning)
        dispatcher.emit_native_events(
            cast("RawClient", batch),
            request_id=7,
            suppress_hook_errors=suppress_request,
        )
        dispatcher.emit_native_events(cast("RawClient", batch), request_id=None, suppress_hook_errors=False)
    assert len(emitted) == 1
    assert isinstance(emitted[0].message, RuntimeWarning)
    assert len(sink.events) == 1
