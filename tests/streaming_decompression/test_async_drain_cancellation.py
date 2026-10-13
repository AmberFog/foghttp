import asyncio

import pytest

import foghttp
from tests.client_telemetry.assertions import assert_stream_completion
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats

from .constants import GZIP_RESERVATION, LARGE_BODY
from .payloads import EncodedResponse, gzip_bytes
from .read_actions import collect_async_into, read_async_until_transport_eof
from .server import ServerFactory


async def test_async_timeout_cancels_decoded_drain_after_transport_eof(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(LARGE_BODY)))
    sink = RecordingTelemetrySink()
    async with foghttp.AsyncClient(
        trust_env=False,
        telemetry=foghttp.TelemetryConfig(sink=sink),
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.aiter_bytes()
            delivered = bytearray(await read_async_until_transport_eof(client, iterator))
            assert 0 < len(delivered) < len(LARGE_BODY)
            assert client.stats().stream_decoder_reserved_bytes == GZIP_RESERVATION
            assert client.stats().active_requests == 1
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0):
                    await collect_async_into(iterator, delivered)
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
                message="cancelled post-EOF drain retained its reservation or request permit",
            )
            client.assert_no_lifecycle_leaks()
            await response.aclose()
        assert client.stats().response_body_aborted == 0
        assert_stream_completion(
            sink.events,
            outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
            error_type="CancelledError",
        )
        finished = [event for event in sink.events if event.event_type == foghttp.TelemetryEventType.REQUEST_FINISHED]
        assert finished[0].response_body_bytes == len(delivered)
        recovery = await client.get(f"{server.url}/healthy")
        assert recovery.headers["x-connection-id"] == response.headers["x-connection-id"]
