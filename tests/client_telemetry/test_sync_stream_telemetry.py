from contextlib import ExitStack

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import SyncStreamingServer
from tests.client_telemetry.assertions import assert_event_types, assert_stream_completion
from tests.client_telemetry.constants import STREAM_EVENT_TYPES
from tests.client_telemetry.models import (
    FailingTelemetrySink,
    FailOnEventTelemetrySink,
    RecordingTelemetrySink,
)
from tests.support.transport_stats import wait_for_sync_transport_stats


def test_sync_stream_full_consume_events(sync_http_server: str) -> None:
    sink = RecordingTelemetrySink()

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{sync_http_server}/bytes/4",
        ) as response,
    ):
        content = b"".join(response.iter_bytes())

    assert content == b"xxxx"
    assert_event_types(sink.events, STREAM_EVENT_TYPES)
    assert sink.events[0].mode == foghttp.TelemetryRequestMode.STREAM
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.SUCCESS)


def test_sync_stream_early_close_events(sync_streaming_server: SyncStreamingServer) -> None:
    sink = RecordingTelemetrySink()

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with (
            foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ) as response,
        ):
            iterator = response.iter_bytes()
            assert stream_readers.next_sync_stream_chunk(iterator) == stream_constants.FIRST_CHUNK

    assert_event_types(sink.events, STREAM_EVENT_TYPES)
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


def test_sync_stream_timeout_uses_public_error(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()
    timeout = foghttp.Timeouts(
        read=stream_constants.READ_TIMEOUT_SECONDS,
        total=stream_constants.STREAM_READ_TIMEOUT,
    )

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{sync_streaming_server.base_url}{stream_constants.SLOW_TAIL_STREAM_PATH}",
            timeout=timeout,
        ) as response,
    ):
        iterator = response.iter_bytes()
        assert stream_readers.next_sync_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
        with pytest.raises(foghttp.ReadTimeout):
            stream_readers.next_sync_stream_chunk(iterator)

    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ReadTimeout",
    )


def test_sync_header_hook_closes_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED)

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            url = f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}"
            with pytest.raises(foghttp.TelemetryHookError), client.stream(GET, url):
                pytest.fail("stream context should not enter after header hook failure")

            sync_streaming_server.release_tail.set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="stream header hook failure should close and abort the streamed body",
            )


def test_sync_close_hook_keeps_body_closed(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with (
            foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ) as response,
        ):
            iterator = response.iter_bytes()
            assert stream_readers.next_sync_stream_chunk(iterator) == stream_constants.FIRST_CHUNK
            with pytest.raises(foghttp.TelemetryHookError):
                response.close()
            response.close()

            sync_streaming_server.release_tail.set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="stream close hook failure should not prevent body cleanup",
            )


def test_sync_hook_ignore_keeps_stream(sync_http_server: str) -> None:
    with (
        foghttp.Client(
            telemetry=foghttp.TelemetryConfig(
                sink=FailingTelemetrySink(),
                on_hook_error="ignore",
            ),
        ) as client,
        client.stream(GET, f"{sync_http_server}/bytes/4") as response,
    ):
        content = b"".join(response.iter_bytes())

    assert content == b"xxxx"
