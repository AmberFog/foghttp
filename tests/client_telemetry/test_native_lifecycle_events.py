import asyncio
from threading import Event, Thread
from urllib.parse import urlsplit

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_keepalive.constants import KEEPALIVE_PATH
from tests.client_keepalive.server import start_keepalive_server
from tests.client_resources.helpers import wait_for_async_stats
from tests.client_streaming import constants as stream_constants
from tests.client_streaming.server import AsyncStreamingServer, SyncStreamingServer
from tests.client_tls.handshake_server import start_tls_handshake_stall_server
from tests.fault_injection.constants import (
    HEALTHY_PATH,
    INCOMPLETE_BODY_PATH,
    SLOW_HEADERS_PATH,
    TOTAL_TIMEOUT,
)
from tests.fault_injection.server import start_fault_injection_server
from tests.support.transport_stats import wait_for_sync_transport_stats

from .models import (
    FailOnceOnEventTelemetrySink,
    FailOnEventTelemetrySink,
    RecordingTelemetrySink,
)


_REQUEST_COUNT = 2
_CLOSE_COMPLETION_TIMEOUT = 1.0


def test_sync_connection_lifecycle_is_correlated_and_redacted() -> None:
    sink = RecordingTelemetrySink()

    with start_keepalive_server() as server:
        url = f"{server.url}{KEEPALIVE_PATH}?token=secret"
        with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            first = client.get(url)
            second = client.get(url)

    assert first.status_code == OK
    assert second.status_code == OK
    request_ids = _request_ids(sink.events)
    assert len(request_ids) == _REQUEST_COUNT
    first_request_id, second_request_id = request_ids
    _assert_successful_acquire(sink.events, request_id=first_request_id)
    _assert_successful_acquire(sink.events, request_id=second_request_id)

    opened = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_OPENED)
    reused = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_REUSED)
    closed = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_CLOSED)
    assert opened.request_id is None
    assert opened.mode is None
    assert opened.method is None
    assert opened.outcome == foghttp.TelemetryRequestOutcome.SUCCESS
    assert reused.request_id == second_request_id
    assert reused.outcome == foghttp.TelemetryRequestOutcome.SUCCESS
    assert closed.request_id is None
    assert closed.mode is None
    assert closed.method is None
    assert closed.outcome == foghttp.TelemetryRequestOutcome.CLOSED
    _assert_native_urls_are_origins(sink.events, expected_origin=server.url)


async def test_async_pool_and_connection_events_are_delivered(http_server: str) -> None:
    sink = RecordingTelemetrySink()

    async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
        response = await client.get(f"{http_server}/status/{OK}")

    assert response.status_code == OK
    request_id = _request_ids(sink.events)[0]
    _assert_successful_acquire(sink.events, request_id=request_id)
    opened = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_OPENED)
    assert opened.request_id is None
    assert opened.mode is None
    assert opened.method is None
    assert opened.outcome == foghttp.TelemetryRequestOutcome.SUCCESS
    closed = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_CLOSED)
    assert closed.request_id is None
    assert closed.outcome == foghttp.TelemetryRequestOutcome.CLOSED


async def test_pool_timeout_has_terminal_error_context(http_server: str) -> None:
    sink = RecordingTelemetrySink()
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    async with foghttp.AsyncClient(
        limits=limits,
        timeouts=timeouts,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        with pytest.raises(foghttp.PoolTimeout):
            await client.get(http_server)

    finished = _single_event(
        sink.events,
        foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
    )
    assert finished.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert finished.error_type == "PoolTimeout"
    assert finished.elapsed_ns is not None
    assert finished.elapsed_ns > 0


async def test_pool_wait_cancellation_is_recorded_once(http_server: str) -> None:
    sink = RecordingTelemetrySink()
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=10)

    async with foghttp.AsyncClient(
        limits=limits,
        timeouts=timeouts,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        task = asyncio.create_task(client.get(http_server))
        await wait_for_async_stats(client, lambda stats: stats.pending_requests == 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    finished_events = _events(
        sink.events,
        foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
    )
    assert len(finished_events) == 1
    assert finished_events[0].outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert finished_events[0].error_type == "CancelledError"


def test_buffered_read_timeout_has_connection_abort_context(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()
    timeouts = foghttp.Timeouts(
        read=stream_constants.READ_TIMEOUT_SECONDS,
        total=stream_constants.STREAM_READ_TIMEOUT,
    )

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        pytest.raises(foghttp.ReadTimeout),
    ):
        client.get(
            f"{sync_streaming_server.base_url}{stream_constants.SLOW_TAIL_STREAM_PATH}",
            timeout=timeouts,
        )

    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert aborted.error_type == "ReadTimeout"


def test_buffered_body_transport_error_uses_public_request_error_category() -> None:
    sink = RecordingTelemetrySink()

    with (
        start_fault_injection_server() as server,
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        pytest.raises(foghttp.RequestError),
    ):
        client.get(server.url + INCOMPLETE_BODY_PATH)

    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert aborted.error_type == "RequestError"


async def test_buffered_body_cancellation_survives_immediate_client_close(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()
    client = foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink))
    raw_client = client._raw_client()  # noqa: SLF001

    try:
        task = asyncio.create_task(
            client.get(
                f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ),
        )
        await streaming_server.first_chunk_sent.wait()
        await wait_for_async_stats(client, lambda stats: stats.buffered_response_bytes > 0)
        task.cancel()
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        streaming_server.release_tail.set()
        await client.aclose()

    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert aborted.error_type == "CancelledError"
    raw_events, dropped_events = raw_client.drain_telemetry_events()
    assert raw_events == []
    assert dropped_events == 0


async def test_pre_header_cancellation_records_assigned_connection_use() -> None:
    sink = RecordingTelemetrySink()

    with start_fault_injection_server() as server:
        async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            task = asyncio.create_task(client.get(server.url + SLOW_HEADERS_PATH))
            await asyncio.to_thread(server.wait_for_path_hits, SLOW_HEADERS_PATH, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert aborted.error_type == "CancelledError"


async def test_client_close_finishes_pending_connection_open() -> None:
    sink = RecordingTelemetrySink()
    client = foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink))
    raw_client = client._raw_client()  # noqa: SLF001

    with start_tls_handshake_stall_server() as server:
        task = asyncio.create_task(client.get(server.url))
        await asyncio.to_thread(server.wait_for_connections, 1)
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task

    failed = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED)
    assert failed.outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert failed.error_type == "CancelledError"
    raw_events, dropped_events = raw_client.drain_telemetry_events()
    assert raw_events == []
    assert dropped_events == 0


def test_pre_header_total_timeout_records_assigned_connection_use() -> None:
    sink = RecordingTelemetrySink()

    with (
        start_fault_injection_server() as server,
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        pytest.raises(foghttp.TimeoutError),
    ):
        client.get(
            server.url + SLOW_HEADERS_PATH,
            timeout=foghttp.Timeouts(total=TOTAL_TIMEOUT),
        )

    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert aborted.error_type == "TimeoutError"


async def test_reused_connection_is_recorded_before_response_headers() -> None:
    sink = RecordingTelemetrySink()

    with start_fault_injection_server() as server:
        async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            first = await client.get(server.url + HEALTHY_PATH)
            task = asyncio.create_task(client.get(server.url + SLOW_HEADERS_PATH))
            await asyncio.to_thread(server.wait_for_path_hits, SLOW_HEADERS_PATH, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert first.status_code == OK
    reused = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_REUSED)
    aborted = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_ABORTED)
    assert reused.request_id == aborted.request_id
    assert aborted.outcome == foghttp.TelemetryRequestOutcome.CANCELLED


def test_ssrf_connection_failure_uses_public_error_category(sync_http_server: str) -> None:
    sink = RecordingTelemetrySink()
    port = urlsplit(sync_http_server).port
    assert port is not None

    with (
        foghttp.Client(
            ssrf=foghttp.SSRFPolicy(),
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        pytest.raises(foghttp.SSRFError),
    ):
        client.get(f"http://localhost:{port}")

    failed = _single_event(sink.events, foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED)
    assert failed.request_id is None
    assert failed.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert failed.error_type == "SSRFError"


async def test_client_close_suppresses_request_owned_native_hook_failure() -> None:
    sink = FailOnEventTelemetrySink(
        fail_on=foghttp.TelemetryEventType.CONNECTION_ABORTED,
    )
    client = foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink))

    with start_fault_injection_server() as server:
        task = asyncio.create_task(client.get(server.url + SLOW_HEADERS_PATH))
        await asyncio.to_thread(server.wait_for_path_hits, SLOW_HEADERS_PATH, 1)
        task.cancel()
        await client.aclose()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_connection_open_failure_has_error_context(unused_tcp_port: int) -> None:
    sink = RecordingTelemetrySink()

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        pytest.raises(foghttp.NetworkError),
    ):
        client.get(f"http://127.0.0.1:{unused_tcp_port}")

    failed = _single_event(
        sink.events,
        foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED,
    )
    assert failed.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert failed.error_type == "NetworkError"
    assert failed.elapsed_ns is not None


def test_total_timeout_during_connection_acquire_has_timeout_context(
    sync_http_server: str,
) -> None:
    sink = RecordingTelemetrySink()
    limits = foghttp.Limits(max_connections=0)
    timeouts = foghttp.Timeouts(pool=1.0, total=TOTAL_TIMEOUT)

    with (
        foghttp.Client(
            limits=limits,
            timeouts=timeouts,
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        pytest.raises(foghttp.TimeoutError),
    ):
        client.get(sync_http_server)

    failed = _single_event(
        sink.events,
        foghttp.TelemetryEventType.CONNECTION_OPEN_FAILED,
    )
    assert failed.request_id is None
    assert failed.outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert failed.error_type == "TimeoutError"


def test_client_scoped_close_is_delivered_on_the_next_request_boundary() -> None:
    sink = RecordingTelemetrySink()

    with start_keepalive_server(disconnect_after_response=True) as server:
        client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink))
        try:
            first = client.get(f"{server.url}{KEEPALIVE_PATH}")
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_connections == 0,
                message="first connection did not close",
            )
            second = client.get(f"{server.url}{KEEPALIVE_PATH}")

            closed = _events(sink.events, foghttp.TelemetryEventType.CONNECTION_CLOSED)
            assert closed
            assert all(event.request_id is None for event in closed)
        finally:
            client.close()

    assert first.status_code == OK
    assert second.status_code == OK


def test_client_scoped_hook_failure_is_deferred_to_client_close() -> None:
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.CONNECTION_CLOSED)

    with start_keepalive_server(disconnect_after_response=True) as server:
        client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink))
        try:
            client.get(f"{server.url}{KEEPALIVE_PATH}")
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_connections == 0,
                message="first connection did not close",
            )

            response = client.get(f"{server.url}{KEEPALIVE_PATH}")
            assert response.status_code == OK

            with pytest.raises(foghttp.TelemetryHookError):
                client.close()
        finally:
            client.close()


def test_client_scoped_hook_failure_does_not_mask_request_error(
    unused_tcp_port: int,
) -> None:
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.CONNECTION_CLOSED)

    with start_keepalive_server(disconnect_after_response=True) as server:
        client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink))
        try:
            client.get(f"{server.url}{KEEPALIVE_PATH}")
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_connections == 0,
                message="first connection did not close",
            )

            with pytest.raises(foghttp.NetworkError):
                client.get(f"http://127.0.0.1:{unused_tcp_port}")
            with pytest.raises(foghttp.TelemetryHookError):
                client.close()
        finally:
            client.close()


def test_connection_close_hook_can_reenter_client_close() -> None:
    sink = _ReentrantCloseTelemetrySink()

    with start_keepalive_server() as server:
        client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink))
        sink.client = client
        client.get(f"{server.url}{KEEPALIVE_PATH}")

        completed = Event()
        errors: list[BaseException] = []

        def close_client() -> None:
            try:
                client.close()
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            finally:
                completed.set()

        thread = Thread(target=close_client, daemon=True)
        thread.start()
        assert completed.wait(timeout=_CLOSE_COMPLETION_TIMEOUT)
        thread.join(timeout=_CLOSE_COMPLETION_TIMEOUT)

    assert not thread.is_alive()
    assert errors == []
    assert sink.reentered


def test_native_hook_failure_uses_existing_raise_policy(sync_http_server: str) -> None:
    sink = FailOnEventTelemetrySink(
        fail_on=foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED,
    )
    client = foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink))
    try:
        with pytest.raises(foghttp.TelemetryHookError):
            client.get(f"{sync_http_server}/status/{OK}")
    finally:
        client.close()


async def test_native_hook_failure_does_not_mask_pool_timeout(http_server: str) -> None:
    sink = FailOnEventTelemetrySink(
        fail_on=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
    )
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)

    async with foghttp.AsyncClient(
        limits=limits,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        with pytest.raises(foghttp.PoolTimeout):
            await client.get(http_server)


def test_disabled_sink_does_not_buffer_native_events(sync_http_server: str) -> None:
    client = foghttp.Client(telemetry=foghttp.TelemetryConfig())
    try:
        response = client.get(f"{sync_http_server}/status/{OK}")
        raw_client = client._raw_client()  # noqa: SLF001
        raw_events, dropped_events = raw_client.drain_telemetry_events()
    finally:
        client.close()

    assert response.status_code == OK
    assert raw_events == []
    assert dropped_events == 0


def _assert_successful_acquire(
    events: list[foghttp.TelemetryEvent],
    *,
    request_id: int,
) -> None:
    started = _single_request_event(
        events,
        foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED,
        request_id=request_id,
    )
    finished = _single_request_event(
        events,
        foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
        request_id=request_id,
    )
    assert started.outcome is None
    assert started.elapsed_ns is None
    assert finished.outcome == foghttp.TelemetryRequestOutcome.SUCCESS
    assert finished.elapsed_ns is not None


def _assert_native_urls_are_origins(
    events: list[foghttp.TelemetryEvent],
    *,
    expected_origin: str,
) -> None:
    native_event_types = {
        foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED,
        foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
        foghttp.TelemetryEventType.CONNECTION_OPENED,
        foghttp.TelemetryEventType.CONNECTION_REUSED,
        foghttp.TelemetryEventType.CONNECTION_CLOSED,
    }
    for event in events:
        if event.event_type not in native_event_types:
            continue
        assert event.origin == expected_origin
        assert event.redacted_url == expected_origin
        assert "secret" not in event.redacted_url
        assert KEEPALIVE_PATH not in event.redacted_url


def _request_ids(events: list[foghttp.TelemetryEvent]) -> tuple[int, ...]:
    return tuple(
        event.request_id
        for event in events
        if event.event_type == foghttp.TelemetryEventType.REQUEST_STARTED and event.request_id is not None
    )


def _single_request_event(
    events: list[foghttp.TelemetryEvent],
    event_type: foghttp.TelemetryEventType,
    *,
    request_id: int,
) -> foghttp.TelemetryEvent:
    matches = tuple(event for event in events if event.event_type == event_type and event.request_id == request_id)
    if len(matches) != 1:
        raise AssertionError((event_type, request_id, len(matches)))
    return matches[0]


def _single_event(
    events: list[foghttp.TelemetryEvent],
    event_type: foghttp.TelemetryEventType,
) -> foghttp.TelemetryEvent:
    matches = _events(events, event_type)
    if len(matches) != 1:
        raise AssertionError((event_type, len(matches)))
    return matches[0]


def _events(
    events: list[foghttp.TelemetryEvent],
    event_type: foghttp.TelemetryEventType,
) -> tuple[foghttp.TelemetryEvent, ...]:
    return tuple(event for event in events if event.event_type == event_type)


class _ReentrantCloseTelemetrySink:
    def __init__(self) -> None:
        self.client: foghttp.Client | None = None
        self.reentered = False

    def emit(self, event: foghttp.TelemetryEvent) -> None:
        if event.event_type != foghttp.TelemetryEventType.CONNECTION_CLOSED or self.reentered:
            return
        self.reentered = True
        assert self.client is not None
        self.client.close()
