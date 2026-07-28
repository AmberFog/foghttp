from contextlib import ExitStack

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import SyncStreamingServer
from tests.client_telemetry.assertions import (
    assert_connection_abort,
    assert_event_types,
    assert_stream_completion,
    assert_stream_request_failure,
)
from tests.client_telemetry.constants import STREAM_EVENT_TYPES
from tests.client_telemetry.models import (
    FailingTelemetrySink,
    FailOnceOnEventTelemetrySink,
    FailOnEventTelemetrySink,
    RecordingTelemetrySink,
)
from tests.support.transport_stats import wait_for_sync_transport_stats


_APPLICATION_BODY_FAILURE = "application body failure"


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
    request_finished = next(
        event for event in sink.events if event.event_type is foghttp.TelemetryEventType.REQUEST_FINISHED
    )
    assert request_finished.response_body_bytes == len(content)


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
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CLOSED,
        error_type=None,
    )
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


def test_sync_line_iteration_counts_bytes_read_into_body_pipeline(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream(
            GET,
            f"{sync_streaming_server.base_url}{stream_constants.TEXT_LINES_STREAM_PATH}",
        ) as response,
    ):
        first_line = next(response.iter_lines())

    request_finished = next(
        event for event in sink.events if event.event_type is foghttp.TelemetryEventType.REQUEST_FINISHED
    )
    assert first_line == stream_constants.TEXT_LINES[0]
    assert request_finished.response_body_bytes is not None
    assert len(first_line.encode()) < request_finished.response_body_bytes
    assert request_finished.response_body_bytes <= len(stream_constants.TEXT_LINES_BODY.encode())


def test_sync_stream_close_before_first_read_has_durations(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = RecordingTelemetrySink()

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with (
            foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            client.stream(
                GET,
                f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ),
        ):
            pass

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
    request_finished = next(
        event for event in sink.events if event.event_type is foghttp.TelemetryEventType.REQUEST_FINISHED
    )
    assert request_finished.response_body_bytes == len(stream_constants.FIRST_CHUNK)
    assert request_finished.timeout_phase == "response_body"
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ReadTimeout",
    )


def test_sync_stream_pre_header_error_has_request_duration(unused_tcp_port: int) -> None:
    sink = RecordingTelemetrySink()

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        pytest.raises(foghttp.NetworkError),
        client.stream(
            GET,
            f"http://127.0.0.1:{unused_tcp_port}/",
            timeout=stream_constants.STREAM_NETWORK_ERROR_TIMEOUTS,
        ),
    ):
        pytest.fail("stream context should not enter after a connection error")

    assert_stream_request_failure(sink.events, error_type="NetworkError")


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


def test_sync_native_hook_failure_releases_stream_with_retained_exception(
    sync_streaming_server: SyncStreamingServer,
    sync_http_server: str,
) -> None:
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.POOL_ACQUIRE_STARTED)

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
            url = f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}"
            with pytest.raises(foghttp.TelemetryHookError) as exc_info, client.stream(GET, url):
                pytest.fail("stream context should not enter after native hook failure")

            retained_error = exc_info.value
            sync_streaming_server.release_tail.set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="native stream hook failure should release the body permit",
            )
            recovery = client.get(f"{sync_http_server}/status/{OK}")

    assert retained_error.__cause__ is not None
    assert recovery.status_code == OK


def test_sync_native_close_hook_does_not_mask_context_body_error(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.CONNECTION_ABORTED)

    with ExitStack() as stack:
        stack.callback(sync_streaming_server.release_tail.set)
        with (
            foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
            pytest.raises(RuntimeError, match=_APPLICATION_BODY_FAILURE),
            client.stream(
                GET,
                f"{sync_streaming_server.base_url}{stream_constants.GATED_STREAM_PATH}",
            ),
        ):
            raise RuntimeError(_APPLICATION_BODY_FAILURE)


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


def test_sync_native_close_hook_error_is_raised_after_body_cleanup(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    sink = FailOnceOnEventTelemetrySink(foghttp.TelemetryEventType.CONNECTION_ABORTED)

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
                message="native close hook failure should not prevent body cleanup",
            )

    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.CLOSED,
        error_type=None,
    )
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.CLOSED)


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
