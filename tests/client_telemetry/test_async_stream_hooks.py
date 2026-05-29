from contextlib import AsyncExitStack

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_telemetry.models import FailingTelemetrySink, FailOnEventTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats


async def test_async_stream_header_hook_closes_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED)

    async with AsyncExitStack() as stack:
        stack.callback(streaming_server.release_tail.set)
        async with foghttp.AsyncClient(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            url = f"{streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}"
            with pytest.raises(foghttp.TelemetryHookError):
                async with client.stream(GET, url):
                    pytest.fail("stream context should not enter after header hook failure")

            streaming_server.release_tail.set()
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="stream header hook failure should close and abort the streamed body",
            )


async def test_async_close_hook_keeps_body_closed(
    streaming_server: AsyncStreamingServer,
) -> None:
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)

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
            with pytest.raises(foghttp.TelemetryHookError):
                await response.aclose()
            await response.aclose()

            streaming_server.release_tail.set()
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="stream close hook failure should not prevent body cleanup",
            )


async def test_async_stream_hook_ignore_keeps_running(http_server: str) -> None:
    async with (
        foghttp.AsyncClient(
            telemetry=foghttp.TelemetryConfig(
                sink=FailingTelemetrySink(),
                on_hook_error="ignore",
            ),
        ) as client,
        client.stream(GET, f"{http_server}/bytes/4") as response,
    ):
        content = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert content == b"xxxx"
