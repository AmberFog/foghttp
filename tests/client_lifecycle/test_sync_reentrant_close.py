from contextlib import nullcontext
from http import HTTPStatus
import subprocess
import sys

import pytest

import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing
from tests.opentelemetry.faults import FaultProvider

from .reentrant_close_helpers import CloseSink, caught_callback, forbid_self_wait, native_stream_read, request_status


_CHILD_TIMEOUT = 8
_STATUS_PATH = "/status/200"


@pytest.mark.parametrize(
    ("mode", "event_type"),
    [
        pytest.param("buffered", foghttp.TelemetryEventType.REQUEST_STARTED, id="buffered-start"),
        pytest.param("buffered", foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED, id="buffered-native"),
        pytest.param("buffered", foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED, id="buffered-headers"),
        pytest.param("buffered", foghttp.TelemetryEventType.REQUEST_FINISHED, id="buffered-finish"),
        pytest.param("stream", foghttp.TelemetryEventType.REQUEST_STARTED, id="stream-start"),
        pytest.param("stream", foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED, id="stream-native"),
        pytest.param("stream", foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED, id="stream-headers"),
    ],
)
def test_caught_reentrant_close_preserves_client_and_send_cleanup(
    sync_http_server: str,
    mode: str,
    event_type: foghttp.TelemetryEventType,
) -> None:
    caught_callback(sync_http_server, mode, event_type, forbid_wait=True)


@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_uncaught_reentrant_close_retains_telemetry_policy(
    sync_http_server: str,
    mode: str,
    policy: foghttp.TelemetryHookErrorPolicy,
) -> None:
    sink = CloseSink(foghttp.TelemetryEventType.REQUEST_STARTED, catch=False)
    provider = FaultProvider()
    client = foghttp.Client(
        telemetry=foghttp.TelemetryConfig(sink, policy),
        tracing=OpenTelemetryTracing(tracer_provider=provider),
        trust_env=False,
    )
    sink.client = client
    expected = pytest.raises(foghttp.TelemetryHookError) if policy == "raise" else nullcontext()
    warning = pytest.warns(RuntimeWarning, match="telemetry event sink failed") if policy == "warn" else nullcontext()
    try:
        with forbid_self_wait(client), expected as caught, warning:
            request_status(client, sync_http_server + _STATUS_PATH, mode)
        if policy == "raise":
            assert isinstance(caught.value.__cause__, foghttp.LifecycleError)
        assert sink.attempts == 1
        assert provider.tracer.spans[0].calls["end"] == 1
        assert not client._active_sync_send_tokens  # noqa: SLF001
        assert client.stats().active_requests == 0
        assert client.get(sync_http_server + _STATUS_PATH).status_code == HTTPStatus.OK
        assert all(span.calls["end"] == 1 for span in provider.tracer.spans)
    finally:
        with forbid_self_wait(client):
            client.close()


@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("stage", ["start", "end"])
def test_reentrant_sdk_close_is_fail_open_without_repeated_span_end(
    sync_http_server: str,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    stage: str,
) -> None:
    provider = FaultProvider()
    client = foghttp.Client(tracing=OpenTelemetryTracing(tracer_provider=provider), trust_env=False)
    attempts: list[str] = []
    original_start = provider.tracer.start_span

    def start_span(*args: object, **kwargs: object) -> object:
        if stage == "start":
            attempts.append(stage)
            client.close()
        span = original_start(*args, **kwargs)
        original_end = span.end

        def end_span(end_time: int | None = None) -> None:
            original_end(end_time=end_time)
            attempts.append(stage)
            client.close()

        monkeypatch.setattr(span, "end", end_span)
        return span

    monkeypatch.setattr(provider.tracer, "start_span", start_span)
    try:
        with forbid_self_wait(client):
            request_status(client, sync_http_server + _STATUS_PATH, mode)
        assert attempts == [stage]
        expected_span_count = 0 if stage == "start" else 1
        assert len(provider.tracer.spans) == expected_span_count
        assert not client._active_sync_send_tokens  # noqa: SLF001
        assert client.stats().active_requests == 0
        assert all(span.calls["end"] == 1 for span in provider.tracer.spans)
        monkeypatch.setattr(provider.tracer, "start_span", original_start)
        assert client.get(sync_http_server + _STATUS_PATH).status_code == HTTPStatus.OK
        assert all(span.calls["end"] == 1 for span in provider.tracer.spans)
    finally:
        with forbid_self_wait(client):
            client.close()


def test_stream_native_drain_rejects_self_close_after_send_token_release() -> None:
    native_stream_read(forbid_wait=True)


def test_stream_finished_callback_can_close_after_native_delivery(sync_http_server: str) -> None:
    completed: list[foghttp.TelemetryEvent] = []
    client: foghttp.Client

    class FinishSink:
        def emit(self, event: foghttp.TelemetryEvent) -> None:
            if event.event_type is foghttp.TelemetryEventType.REQUEST_FINISHED:
                completed.append(event)
                client.close()

    client = foghttp.Client(telemetry=foghttp.TelemetryConfig(FinishSink()), trust_env=False)
    with forbid_self_wait(client):
        request_status(client, sync_http_server + _STATUS_PATH, "stream")
    assert len(completed) == 1
    assert client._close_complete  # noqa: SLF001
    client.close()


def test_observer_can_close_a_different_idle_client(sync_http_server: str) -> None:
    other = foghttp.Client(trust_env=False)
    assert other.get(sync_http_server + _STATUS_PATH).status_code == HTTPStatus.OK

    class OtherClientSink:
        def emit(self, event: foghttp.TelemetryEvent) -> None:
            if event.event_type is foghttp.TelemetryEventType.REQUEST_STARTED:
                other.close()

    try:
        with foghttp.Client(telemetry=foghttp.TelemetryConfig(OtherClientSink()), trust_env=False) as client:
            assert client.get(sync_http_server + _STATUS_PATH).status_code == HTTPStatus.OK
            assert other._close_complete  # noqa: SLF001
            assert client.get(sync_http_server + _STATUS_PATH).status_code == HTTPStatus.OK
    finally:
        other.close()


@pytest.mark.parametrize("scenario", ["request_started", "concurrent_nested", "stream_native_read"])
def test_reentrant_close_completes_under_real_waits(sync_http_server: str, scenario: str) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tests.client_lifecycle.reentrant_close_probe", scenario, sync_http_server],
        check=False,
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
