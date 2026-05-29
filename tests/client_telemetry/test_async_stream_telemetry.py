import asyncio
from contextlib import AsyncExitStack

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_telemetry.assertions import assert_event_types
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
    assert sink.events[-2].outcome == foghttp.TelemetryRequestOutcome.SUCCESS
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.SUCCESS


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
    assert sink.events[-2].outcome == foghttp.TelemetryRequestOutcome.CLOSED
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.CLOSED


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

    assert sink.events[-2].outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert sink.events[-2].error_type == "ReadTimeout"
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert sink.events[-1].error_type == "ReadTimeout"


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

    assert sink.events[-2].outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert sink.events[-2].error_type == "CancelledError"
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.CANCELLED
    assert sink.events[-1].error_type == "CancelledError"


async def _cancel_pending_stream_read(response: foghttp.AsyncStreamResponse) -> None:
    iterator = response.aiter_bytes()
    assert await stream_readers.next_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
    pending_chunk = asyncio.create_task(anext(iterator))
    await stream_readers.wait_for_pending_chunk_task(pending_chunk)

    pending_chunk.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_chunk
