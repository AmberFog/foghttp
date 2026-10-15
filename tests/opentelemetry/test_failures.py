__all__ = ("sync_blocking_http_server",)

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from http import HTTPStatus
import logging
import threading
from typing import Any
import weakref

from opentelemetry import context, trace
import pytest

import foghttp
from foghttp.opentelemetry import OpenTelemetryTracing
from tests.client_lifecycle.conftest import sync_blocking_http_server
from tests.client_lifecycle.constants import BLOCKING_RESPONSE_PATH
from tests.client_lifecycle.helpers import BlockingSyncHTTPServer, wait_until_sync_client_closed
from tests.client_telemetry.models import FailOnEventTelemetrySink
from tests.streaming_decompression.payloads import gated_gzip
from tests.streaming_decompression.server import ServerFactory
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats

from .actions import close_client, request_status
from .faults import FaultProvider, InstrumentationInterrupt


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("stage", ["capture", "start", "recording", "attribute", "status", "end"])
async def test_ordinary_sdk_fault_is_fail_open_and_next_request_can_trace(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    client_type: Any,
    mode: str,
    stage: str,
) -> None:
    failure = RuntimeError("sdk-secret-message")
    faults = {stage: failure}
    provider = FaultProvider(faults)
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    original_capture = context.get_current

    def capture() -> context.Context:
        if "capture" in faults:
            raise failure
        return original_capture()

    monkeypatch.setattr(context, "get_current", capture)
    client = client_type(tracing=tracing, trust_env=False)
    try:
        status = await request_status(client, f"{sync_http_server}/status/503", mode)
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        expected_spans = 0 if stage in {"capture", "start"} else 1
        assert len(provider.tracer.spans) == expected_spans
        for span in provider.tracer.spans:
            assert span.calls["end"] == 1
        faults.clear()
        assert await request_status(client, sync_http_server, mode) == HTTPStatus.OK
        assert len(provider.tracer.spans) == expected_spans + 1
        assert provider.tracer.spans[-1].calls["end"] == 1
    finally:
        await close_client(client)


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("primary_type", [foghttp.NetworkError, asyncio.CancelledError])
@pytest.mark.parametrize("fault_type", [RuntimeError, InstrumentationInterrupt])
async def test_secondary_sdk_faults_preserve_primary_error_and_end_once(
    monkeypatch: pytest.MonkeyPatch,
    client_type: Any,
    mode: str,
    primary_type: type[BaseException],
    fault_type: type[BaseException],
) -> None:
    primary = primary_type("primary-error")
    provider = FaultProvider({"recording": fault_type("secondary-recording"), "end": fault_type("secondary-end")})
    tracing = OpenTelemetryTracing(tracer_provider=provider)

    def fail_sync(*_args: object, **_kwargs: object) -> None:
        raise primary

    async def fail_async(*_args: object, **_kwargs: object) -> None:
        raise primary

    method = "_transport_send" if mode == "buffered" else "_transport_stream"
    monkeypatch.setattr(client_type, method, fail_sync if client_type is foghttp.Client else fail_async)
    client = client_type(tracing=tracing, trust_env=False)
    try:
        with pytest.raises(primary_type) as caught:
            await request_status(client, "http://example.invalid", mode)
        assert caught.value is primary
        span = provider.tracer.spans[0]
        assert span.calls["end"] == 1
        assert span.status is trace.StatusCode.UNSET
    finally:
        await close_client(client)


@pytest.mark.parametrize("stage", ["capture", "start", "recording", "attribute", "status", "end"])
def test_sdk_control_flow_propagates_without_primary_error(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    stage: str,
) -> None:
    failure = InstrumentationInterrupt("sdk-interruption")
    provider = FaultProvider({stage: failure})
    tracing = OpenTelemetryTracing(tracer_provider=provider)

    def interrupted_capture() -> None:
        raise failure

    if stage == "capture":
        monkeypatch.setattr(context, "get_current", interrupted_capture)
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        with pytest.raises(InstrumentationInterrupt) as caught:
            client.get(f"{sync_http_server}/status/503")
        assert caught.value is failure
        expected_spans = 0 if stage in {"capture", "start"} else 1
        assert len(provider.tracer.spans) == expected_spans
        for span in provider.tracer.spans:
            assert span.calls["end"] == 1


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
@pytest.mark.parametrize("stage", ["recording", "end"])
async def test_stream_finish_interrupt_releases_resources_with_retained_traceback(
    decompression_server: ServerFactory,
    client_type: Any,
    stage: str,
    *,
    decode_content: bool,
) -> None:
    server = decompression_server(gated_gzip())
    failure = InstrumentationInterrupt("unhanded-stream")
    provider = FaultProvider({stage: failure})
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    client = client_type(tracing=tracing, trust_env=False, limits=foghttp.Limits(max_active_requests=1))
    try:
        with pytest.raises(InstrumentationInterrupt) as caught:
            await request_status(client, server.url, "stream", decode_content=decode_content)
        retained_error = caught.value
        assert retained_error is failure
        assert retained_error.__traceback__ is not None
        assert provider.tracer.spans[0].calls["end"] == 1

        def released(stats: foghttp.TransportStats) -> bool:
            return stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0

        if isinstance(client, foghttp.Client):
            wait_for_sync_transport_stats(client, released, message="interrupted stream retained resources")
        else:
            await wait_for_async_transport_stats(client, released, message="interrupted stream retained resources")
        assert client.stats().response_body_aborted == 1
        provider.tracer.faults.clear()
        assert await request_status(client, f"{server.url}/healthy", "buffered") == HTTPStatus.OK
        assert retained_error.__traceback__ is not None
        assert provider.tracer.spans[0].calls["end"] == 1
    finally:
        server.release_tail.set()
        await close_client(client)


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
async def test_stream_close_failure_does_not_replace_instrumentation_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    client_type: Any,
) -> None:
    failure = InstrumentationInterrupt("original-interruption")
    provider = FaultProvider({"end": failure})
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    response_type = foghttp.StreamResponse if client_type is foghttp.Client else foghttp.AsyncStreamResponse
    close_attempts: list[object] = []
    original_close = response_type.close

    def close_then_fail(response: Any) -> None:
        close_attempts.append(response)
        original_close(response)
        message = "cleanup-interruption"
        raise InstrumentationInterrupt(message)

    monkeypatch.setattr(response_type, "close", close_then_fail)
    client = client_type(tracing=tracing, trust_env=False)
    try:
        with pytest.raises(InstrumentationInterrupt) as caught:
            await request_status(client, sync_http_server, "stream")
        assert caught.value is failure
        assert len(close_attempts) == 1
        assert provider.tracer.spans[0].calls["end"] == 1
    finally:
        await close_client(client)


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("before_result", [False, True], ids=["after-result", "before-result"])
async def test_tracing_preserves_user_hook_policy_and_http_outcome(
    sync_http_server: str,
    client_type: Any,
    mode: str,
    policy: foghttp.TelemetryHookErrorPolicy,
    *,
    before_result: bool,
) -> None:
    event = (
        foghttp.TelemetryEventType.REQUEST_STARTED
        if before_result
        else foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED
    )
    sink = FailOnEventTelemetrySink(event)
    provider = FaultProvider()
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    client = client_type(tracing=tracing, telemetry=foghttp.TelemetryConfig(sink, policy), trust_env=False)
    outcome = pytest.raises(foghttp.TelemetryHookError) if policy == "raise" else nullcontext()
    warning = pytest.warns(RuntimeWarning, match="telemetry event sink failed") if policy == "warn" else nullcontext()
    try:
        with outcome, warning:
            assert await request_status(client, sync_http_server, mode) == HTTPStatus.OK
        span = provider.tracer.spans[0]
        assert span.calls["end"] == 1
        if before_result and policy == "raise":
            assert span.status is trace.StatusCode.ERROR
            assert span.attributes["error.type"] == "FogHTTPError"
            assert "http.response.status_code" not in span.attributes
        else:
            assert span.status is trace.StatusCode.UNSET
            assert span.attributes["http.response.status_code"] == HTTPStatus.OK
            assert "error.type" not in span.attributes
    finally:
        await close_client(client)


def test_nonrecording_span_is_ended_without_terminal_attributes(sync_http_server: str) -> None:
    provider = FaultProvider(recording=False)
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        assert client.get(f"{sync_http_server}/status/503").status_code == HTTPStatus.SERVICE_UNAVAILABLE
    span = provider.tracer.spans[0]
    assert span.calls["end"] == 1
    assert span.calls["attribute"] == span.calls["status"] == 0


def test_diagnostics_are_safe_and_bounded_across_concurrent_clients(
    sync_http_server: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FaultProvider({"end": RuntimeError("sdk-secret-credential")})
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    workers = 4
    barrier = threading.Barrier(workers)

    def request(_index: int) -> int:
        barrier.wait(timeout=5)
        with foghttp.Client(tracing=tracing, trust_env=False) as client:
            return client.get(f"{sync_http_server}/private-secret?token=url-secret").status_code

    with caplog.at_level(logging.DEBUG, logger="foghttp"), ThreadPoolExecutor(max_workers=workers) as executor:
        assert list(executor.map(request, range(workers))) == [HTTPStatus.OK] * workers
    records = [record for record in caplog.records if record.name.startswith("foghttp")]
    assert len(records) == 1
    record = records[0]
    assert record.args == ()
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.stack_info is None
    assert all(secret not in repr(record.__dict__) for secret in ("sdk-secret", "private-secret", "url-secret"))
    assert all(span.calls["end"] == 1 for span in provider.tracer.spans)


@pytest.mark.parametrize("log_failure", [RuntimeError, InstrumentationInterrupt])
@pytest.mark.parametrize("primary", [False, True], ids=["response", "primary-error"])
def test_diagnostic_failure_preserves_failure_policy(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_server: str,
    log_failure: type[BaseException],
    *,
    primary: bool,
) -> None:
    provider = FaultProvider({"end": RuntimeError("sdk-failure")})
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    logging_error = log_failure("logging-failure")
    primary_error = foghttp.NetworkError("transport-failure")
    records: list[logging.LogRecord] = []

    def fail_logging(_logger: logging.Logger, record: logging.LogRecord) -> None:
        records.append(record)
        raise logging_error

    def fail_transport(*_args: object, **_kwargs: object) -> None:
        raise primary_error

    monkeypatch.setattr(logging.Logger, "handle", fail_logging)
    if primary:
        monkeypatch.setattr(foghttp.Client, "_transport_send", fail_transport)
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        expected = primary_error if primary else logging_error
        if primary or log_failure is InstrumentationInterrupt:
            with pytest.raises(type(expected)) as caught:
                client.get(sync_http_server)
            assert caught.value is expected
        else:
            assert client.get(sync_http_server).status_code == HTTPStatus.OK
    assert len(records) == 1
    assert provider.tracer.spans[0].calls["end"] == 1


def test_completed_execution_does_not_retain_request_or_extensions(sync_http_server: str) -> None:
    class Request(foghttp.Request):
        """Allow weak references without changing the public request contract."""

    class Sentinel:
        """Detect retention of arbitrary caller extensions."""

    provider = FaultProvider()
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    sentinel = Sentinel()
    request = Request("POST", sync_http_server, content=b"private-body", extensions={"sentinel": sentinel})
    request_ref, sentinel_ref = weakref.ref(request), weakref.ref(sentinel)
    with foghttp.Client(tracing=tracing, trust_env=False) as client:
        response = client.send(request)
        assert response.status_code == HTTPStatus.OK
        del response, request, sentinel
        assert request_ref() is None
        assert sentinel_ref() is None
    assert provider.tracer.spans[0].calls["end"] == 1


@pytest.mark.parametrize("mode", ["buffered", "stream"])
async def test_cancelling_running_request_ends_span_after_unwind_and_releases_native_resources(
    sync_blocking_http_server: BlockingSyncHTTPServer,
    mode: str,
) -> None:
    server = sync_blocking_http_server
    provider = FaultProvider({"end": InstrumentationInterrupt("secondary-cancellation-cleanup")})
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    async with foghttp.AsyncClient(tracing=tracing, trust_env=False) as client:
        task = asyncio.create_task(request_status(client, server.base_url + BLOCKING_RESPONSE_PATH, mode))
        try:
            assert await asyncio.to_thread(server.request_started.wait, 1)
            assert client.stats().active_requests == 1
            span = provider.tracer.spans[0]
            assert span.calls["end"] == 0
            task.cancel("cancel-before-headers")
            with pytest.raises(asyncio.CancelledError, match="cancel-before-headers"):
                await task
            assert task.cancelled()
            assert span.calls["end"] == 1
            assert span.status is trace.StatusCode.UNSET
            assert "error.type" not in span.attributes
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0,
                message="cancelled traced request retained native ownership",
            )
        finally:
            server.release_response.set()
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task


def test_sync_close_does_not_finish_span_before_inflight_request_returns(
    sync_blocking_http_server: BlockingSyncHTTPServer,
) -> None:
    server = sync_blocking_http_server
    provider = FaultProvider()
    tracing = OpenTelemetryTracing(tracer_provider=provider)
    client = foghttp.Client(tracing=tracing, trust_env=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        request_future = executor.submit(client.get, server.base_url + BLOCKING_RESPONSE_PATH)
        try:
            assert server.request_started.wait(timeout=1)
            span = provider.tracer.spans[0]
            assert span.calls["end"] == 0
            close_future = executor.submit(client.close)
            wait_until_sync_client_closed(client)
            assert not close_future.done()
            assert span.calls["end"] == 0
            server.release_response.set()
            assert request_future.result(timeout=2).status_code == HTTPStatus.OK
            close_future.result(timeout=2)
            assert span.calls["end"] == 1
            assert span.attributes["http.response.status_code"] == HTTPStatus.OK
        finally:
            server.release_response.set()
            client.close()


@pytest.mark.parametrize("client_type", [foghttp.Client, foghttp.AsyncClient])
@pytest.mark.parametrize("mode", ["buffered", "stream"])
@pytest.mark.parametrize("stage", ["recording", "end"])
async def test_handled_caller_error_does_not_suppress_new_sdk_interruption(
    sync_http_server: str,
    client_type: Any,
    mode: str,
    stage: str,
) -> None:
    failure = InstrumentationInterrupt("current-instrumentation-interruption")
    faults: dict[str, BaseException] = {"end": InstrumentationInterrupt("secondary-end-interruption")}
    faults[stage] = failure
    provider = FaultProvider(faults)
    client = client_type(tracing=OpenTelemetryTracing(tracer_provider=provider))
    try:
        try:
            int("previously-handled-caller-error")
        except ValueError:
            with pytest.raises(InstrumentationInterrupt) as caught:
                await request_status(client, sync_http_server, mode)
            assert caught.value is failure
        assert provider.tracer.spans[0].calls["end"] == 1
        assert client.stats().active_requests == 0
    finally:
        await close_client(client)


@pytest.mark.parametrize("mode", ["buffered", "stream"])
async def test_async_close_finishes_span_only_when_request_unwinds(
    sync_blocking_http_server: BlockingSyncHTTPServer,
    mode: str,
) -> None:
    server = sync_blocking_http_server
    provider = FaultProvider()
    client = foghttp.AsyncClient(tracing=OpenTelemetryTracing(tracer_provider=provider))
    task = asyncio.create_task(request_status(client, server.base_url + BLOCKING_RESPONSE_PATH, mode))
    try:
        assert await asyncio.to_thread(server.request_started.wait, 1)
        span = provider.tracer.spans[0]
        assert span.calls["end"] == 0
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert span.calls["end"] == 1
        assert span.status is trace.StatusCode.UNSET
        assert "error.type" not in span.attributes
        client.assert_no_lifecycle_leaks()
    finally:
        server.release_response.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await client.aclose()
