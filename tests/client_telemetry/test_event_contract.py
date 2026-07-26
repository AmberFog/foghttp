from collections.abc import Callable
from dataclasses import fields
from threading import Event, Thread
from types import SimpleNamespace
from typing import cast

import pytest

import foghttp
from foghttp._client.telemetry import (
    NativeTelemetryDrain,
    TelemetryDispatcher,
    TelemetryRequestContext,
    start_request_telemetry,
)
from foghttp._client.telemetry.emission import TelemetryCompletion
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from foghttp._telemetry import TELEMETRY_EVENT_SCHEMA_VERSION
from foghttp.methods import GET
import foghttp.stream_response.telemetry as stream_telemetry
from foghttp.stream_response.telemetry import StreamResponseTelemetryMixin
from foghttp.telemetry import TelemetryConfig, TelemetryEvent, TelemetryEventType, TelemetryRequestMode
from tests.client_telemetry.models import RecordingTelemetrySink


EXPECTED_EVENT_SCHEMA_VERSION = 3
_DELIVERY_TIMEOUT = 1.0
_REQUEST_NOT_RELEASED = "request delivery was not released"
_REQUEST_STARTED_AT_NS = 100
_BODY_STARTED_AT_NS = 200
_COMPLETED_AT_NS = 500


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://example.com:443/path?token=secret", id="default-port"),
        pytest.param("http://[::1]:80/path", id="ipv6-default-port"),
        pytest.param("https://example.com:444/path", id="non-default-port"),
    ],
)
def test_request_origin_matches_url_model(url: str) -> None:
    sink = RecordingTelemetrySink()
    dispatcher = TelemetryDispatcher(TelemetryConfig(sink=sink))
    telemetry_context = dispatcher.request_context(
        foghttp.Request(GET, url),
        mode=TelemetryRequestMode.BUFFERED,
    )

    assert start_request_telemetry(telemetry_context)

    assert sink.events[0].origin == foghttp.URL(url).origin


def test_event_schema_uses_event_constant() -> None:
    event = TelemetryEvent(
        event_type=TelemetryEventType.REQUEST_STARTED,
        event_sequence=1,
        observed_at_ns=1,
    )

    assert event.schema_version == TELEMETRY_EVENT_SCHEMA_VERSION
    assert event.schema_version == EXPECTED_EVENT_SCHEMA_VERSION
    assert event.body_elapsed_ns is None
    assert event.request_elapsed_ns is None


def test_duration_fields_preserve_existing_positional_event_contract() -> None:
    field_names = tuple(field.name for field in fields(TelemetryEvent))

    assert field_names[field_names.index("schema_version") :] == (
        "schema_version",
        "body_elapsed_ns",
        "request_elapsed_ns",
    )


def test_stream_completion_timestamp_precedes_observer_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    context = _TimingTelemetryContext(calls)
    response = _StreamTelemetryHarness(
        context=context,
        finish_native=_record_native_finish(calls),
        calls=calls,
    )

    def completion_clock() -> int:
        calls.append("clock")
        return _COMPLETED_AT_NS

    monkeypatch.setattr(
        stream_telemetry,
        "time",
        SimpleNamespace(perf_counter_ns=completion_clock),
    )

    response.finish()

    assert calls == ["clock", "lifecycle_debug", "native", "body", "request"]
    expected_durations = (
        _COMPLETED_AT_NS - _BODY_STARTED_AT_NS,
        _COMPLETED_AT_NS - _REQUEST_STARTED_AT_NS,
    )
    assert tuple((completion.body_elapsed_ns, completion.request_elapsed_ns) for completion in context.completions) == (
        expected_durations,
        expected_durations,
    )


def test_native_journal_overflow_uses_hook_error_policy() -> None:
    dispatcher = TelemetryDispatcher(TelemetryConfig(sink=RecordingTelemetrySink()))

    with pytest.raises(foghttp.TelemetryHookError):
        dispatcher.emit_native_events(
            cast("_foghttp.RawClient", _DroppedEventRawClient()),
            request_id=None,
            suppress_hook_errors=False,
        )


def test_client_close_waits_for_request_delivery_before_raising_client_error() -> None:
    dispatcher = TelemetryDispatcher(TelemetryConfig(sink=RecordingTelemetrySink()))
    raw_client = _BlockingDroppedEventRawClient()
    request_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    close_finished = Event()

    def deliver_request() -> None:
        try:
            dispatcher.emit_native_events(
                cast("_foghttp.RawClient", raw_client),
                request_id=1,
                suppress_hook_errors=False,
            )
        except BaseException as error:  # noqa: BLE001
            request_errors.append(error)

    def close_delivery() -> None:
        try:
            dispatcher.emit_native_events(
                cast("_foghttp.RawClient", raw_client),
                request_id=None,
                suppress_hook_errors=False,
            )
        except BaseException as error:  # noqa: BLE001
            close_errors.append(error)
        finally:
            close_finished.set()

    request_thread = Thread(target=deliver_request, daemon=True)
    request_thread.start()
    assert raw_client.request_started.wait(timeout=_DELIVERY_TIMEOUT)
    close_thread = Thread(target=close_delivery, daemon=True)
    close_thread.start()
    assert not close_finished.wait(timeout=0.05)

    raw_client.release_request.set()
    request_thread.join(timeout=_DELIVERY_TIMEOUT)
    close_thread.join(timeout=_DELIVERY_TIMEOUT)

    assert not request_thread.is_alive()
    assert not close_thread.is_alive()
    assert request_errors == []
    assert len(close_errors) == 1
    assert isinstance(close_errors[0], foghttp.TelemetryHookError)


def test_request_redacts_url_secret_parts() -> None:
    redacted_url = _start_event_redacted_url(_url_with_secret_parts())
    assert redacted_url is not None
    assert "<redacted>@example.com" in redacted_url
    assert "hunter" not in redacted_url
    assert "secret" not in redacted_url


def _start_event_redacted_url(url: str) -> str | None:
    sink = RecordingTelemetrySink()
    telemetry_context = TelemetryDispatcher(TelemetryConfig(sink=sink)).request_context(
        foghttp.Request(GET, url),
        mode=TelemetryRequestMode.BUFFERED,
    )
    assert start_request_telemetry(telemetry_context)
    return sink.events[0].redacted_url


def _url_with_secret_parts() -> str:
    userinfo = "user:hunter"
    return f"https://{userinfo}@example.com/path?token=secret#section?password=secret"


class _DroppedEventRawClient:
    def drain_telemetry_events(
        self,
        request_id: int | None = None,
    ) -> tuple[list[_foghttp.RawTelemetryEvent], int]:
        assert request_id is None
        return [], 1


class _TimingTelemetryContext:
    def __init__(self, calls: list[str]) -> None:
        self.started_at_ns = _REQUEST_STARTED_AT_NS
        self.completions: list[TelemetryCompletion] = []
        self._calls = calls

    def response_body_finished(self, completion: TelemetryCompletion) -> None:
        self._calls.append("body")
        self.completions.append(completion)

    def request_finished(self, completion: TelemetryCompletion) -> None:
        self._calls.append("request")
        self.completions.append(completion)


def _record_native_finish(calls: list[str]) -> Callable[..., None]:
    def finish(*, suppress_hook_errors: bool) -> None:
        assert not suppress_hook_errors
        calls.append("native")

    return finish


class _StreamTelemetryHarness(StreamResponseTelemetryMixin):
    def __init__(
        self,
        *,
        context: _TimingTelemetryContext,
        finish_native: Callable[..., None],
        calls: list[str],
    ) -> None:
        self.status_code = 200
        self.url = "https://example.com/"
        self._telemetry_context = cast("TelemetryRequestContext", context)
        self._telemetry_body_started_at_ns = _BODY_STARTED_AT_NS
        self._native_telemetry_finish = cast("NativeTelemetryDrain", finish_native)
        self._telemetry_finished = False
        self._calls = calls

    def finish(self) -> None:
        self._finish_observability(
            outcome=foghttp.TelemetryRequestOutcome.SUCCESS,
            suppress_hook_errors=False,
        )

    def _finish_lifecycle_debug(self) -> None:
        self._calls.append("lifecycle_debug")


class _BlockingDroppedEventRawClient:
    def __init__(self) -> None:
        self.request_started = Event()
        self.release_request = Event()

    def drain_telemetry_events(
        self,
        request_id: int | None = None,
    ) -> tuple[list[_foghttp.RawTelemetryEvent], int]:
        if request_id is None:
            return [], 0
        self.request_started.set()
        if not self.release_request.wait(timeout=_DELIVERY_TIMEOUT):
            raise AssertionError(_REQUEST_NOT_RELEASED)
        return [], 1
