import asyncio
from contextlib import AsyncExitStack
import time
from types import SimpleNamespace

import pytest

import foghttp
from foghttp.methods import GET
import foghttp.stream_response.bindings as stream_bindings
import foghttp.stream_response.telemetry as stream_telemetry
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_telemetry.assertions import (
    assert_connection_abort,
    assert_event_types,
    assert_stream_completion,
    assert_stream_request_failure,
)
from tests.client_telemetry.constants import STREAM_EVENT_TYPES
from tests.client_telemetry.models import RecordingTelemetrySink


async def test_async_stream_full_consume_events(http_server: str) -> None:
    sink = RecordingTelemetrySink()

    async with (
        foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{http_server}/bytes/4",
        ) as response,
    ):
        content = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert content == b"xxxx"
    assert_event_types(sink.events, STREAM_EVENT_TYPES)
    assert sink.events[0].mode == foghttp.TelemetryRequestMode.STREAM
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.SUCCESS)


async def test_async_stream_early_close_events(streaming_server: AsyncStreamingServer) -> None:
    sink = RecordingTelemetrySink()

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with (
            foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ) as response,
        ):
            iterator = response.aiter_bytes()
            assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK

    assert_event_types(sink.events, STREAM_EVENT_TYPES)
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CLOSED,
        error_type=None,
    )
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


async def test_async_stream_close_before_first_read_has_durations(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with (
            foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ),
        ):
            pass

    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


async def test_async_stream_timeout_uses_public_error(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()
    timeout = foghttp.Timeouts(
        read=stream_constants.READ_TIMEOUT_SECONDS,
        total=stream_constants.STREAM_READ_TIMEOUT,
    )

    async with (
        foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{streaming_server.base_url}{stream_constants.SLOW_TAIL_STREAM_PATH}",
            timeout=timeout,
        ) as response,
    ):
        iterator = response.aiter_bytes()
        assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
        with pytest.raises(foghttp.ReadTimeout):
            await stream_readers.next_stream_chunk(iterator)

    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ReadTimeout",
    )
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ReadTimeout",
    )


async def test_async_stream_read_cancel_emits_cancelled(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with (
            foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ) as response,
        ):
            await _cancel_pending_stream_read(response)

    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
        error_type="CancelledError",
    )
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
        error_type="CancelledError",
    )


@pytest.mark.parametrize(
    "chunks_before_cancel",
    [0, 1],
    ids=("before-first-read", "between-reads"),
)
async def test_async_stream_context_cancel_emits_cancelled(
    streaming_server: AsyncStreamingServer,
    chunks_before_cancel: int,
) -> None:
    sink = RecordingTelemetrySink()

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            stream_task = asyncio.create_task(
                _cancel_inside_stream_context(
                    client,
                    streaming_server,
                    chunks_before_cancel=chunks_before_cancel,
                ),
            )
            with pytest.raises(asyncio.CancelledError):
                await stream_task

            stats = client.stats()
            assert (stats.active_requests, stats.response_body_aborted) == (0, 1)

    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
        error_type="CancelledError",
    )
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
        error_type="CancelledError",
    )


async def test_async_stream_duration_boundaries_follow_handoff_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    streaming_server: AsyncStreamingServer,
) -> None:
    calls: list[str] = []
    sink = RecordingTelemetrySink()
    client = foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink))

    def body_clock() -> int:
        assert any(event.event_type is foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED for event in sink.events)
        calls.append("body_clock")
        return time.perf_counter_ns()

    def terminal_clock() -> int:
        stats = client.stats()
        assert (stats.active_requests, stats.response_body_aborted) == (0, 1)
        calls.append("terminal_clock")
        return time.perf_counter_ns()

    monkeypatch.setattr(stream_bindings, "time", SimpleNamespace(perf_counter_ns=body_clock))
    monkeypatch.setattr(stream_telemetry, "time", SimpleNamespace(perf_counter_ns=terminal_clock))

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with (
            client,
            client.stream(
                GET,
                f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ),
        ):
            calls.append("handoff")

    assert calls == ["body_clock", "handoff", "terminal_clock"]
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


async def test_async_stream_body_error_has_durations(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()

    async with (
        foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{streaming_server.base_url}{stream_constants.BROKEN_READY_TAIL_STREAM_PATH}",
        ) as response,
    ):
        iterator = response.aiter_bytes()
        assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
        assert await stream_readers.next_stream_chunk(iterator) == stream_constants.SECOND_CHUNK
        with pytest.raises(foghttp.RequestError):
            await stream_readers.next_stream_chunk(iterator)

    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="RequestError",
    )


async def test_async_stream_pre_header_error_has_request_duration(unused_tcp_port: int) -> None:
    sink = RecordingTelemetrySink()

    async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
        with pytest.raises(foghttp.NetworkError):
            async with client.stream(
                GET,
                f"http://127.0.0.1:{unused_tcp_port}/",
                timeout=stream_constants.STREAM_NETWORK_ERROR_TIMEOUTS,
            ):
                pytest.fail("stream context should not enter after a connection error")

    assert_stream_request_failure(sink.events, error_type="NetworkError")


async def _cancel_pending_stream_read(response: foghttp.AsyncStreamResponse) -> None:
    iterator = response.aiter_bytes()
    assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
    pending_chunk = asyncio.create_task(anext(iterator))
    await stream_readers.wait_for_pending_chunk_task(pending_chunk)

    pending_chunk.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_chunk


async def _cancel_inside_stream_context(
    client: foghttp.AsyncClient,
    streaming_server: AsyncStreamingServer,
    *,
    chunks_before_cancel: int,
) -> None:
    async with client.stream(
        GET,
        f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
    ) as response:
        if chunks_before_cancel:
            iterator = response.aiter_bytes()
            assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
        current_task = asyncio.current_task()
        assert current_task is not None
        current_task.cancel()
        await asyncio.sleep(0)
