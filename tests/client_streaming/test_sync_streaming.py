from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.client_streaming.constants import (
    EMPTY_STREAM_PATH,
    FIRST_CHUNK,
    GATED_STREAM_PATH,
    READ_TIMEOUT_SECONDS,
    SECOND_CHUNK,
    SLOW_TAIL_STREAM_PATH,
    STREAM_NETWORK_ERROR_TIMEOUTS,
    STREAM_READ_TIMEOUT,
)
from tests.client_streaming.server import SyncStreamingServer
from tests.client_streaming.stream_readers import (
    collect_sync_stream_chunks,
    next_sync_stream_chunk,
    wait_for_pending_sync_chunk_future,
)
from tests.support.transport_stats import wait_for_sync_transport_stats


def test_sync_stream_enters_after_headers_without_buffering_tail(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with foghttp.Client() as client:
        with client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            assert response.status_code == OK
            response.raise_for_status()
            assert not sync_streaming_server.release_tail.is_set()

            byte_stream = response.iter_bytes()
            first = next_sync_stream_chunk(byte_stream)
            assert first == FIRST_CHUNK
            assert not sync_streaming_server.release_tail.is_set()

            sync_streaming_server.release_tail.set()
            remaining = collect_sync_stream_chunks(byte_stream)
            assert [first, *remaining] == [FIRST_CHUNK, SECOND_CHUNK]

        assert client.stats().failed_requests == 0
        assert client.stats().response_body_closed == 1


def test_sync_stream_empty_body_reaches_clean_eof(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with foghttp.Client() as client:
        with client.stream(GET, f"{sync_streaming_server.base_url}{EMPTY_STREAM_PATH}") as response:
            assert collect_sync_stream_chunks(response.iter_bytes()) == []

        stats = client.stats()
        assert stats.failed_requests == 0
        assert stats.response_body_closed == 1
        assert stats.response_body_aborted == 0


def test_sync_stream_context_is_single_use(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        context = client.stream(GET, f"{sync_http_server}/status/{OK}")
        with context as response:
            assert response.status_code == OK

        with pytest.raises(foghttp.LifecycleError, match="stream context cannot be entered more than once"):
            context.__enter__()


def test_sync_stream_context_abort_releases_active_request_slot(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with foghttp.Client() as client:
        with client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            byte_stream = response.iter_bytes()
            assert next_sync_stream_chunk(byte_stream) == FIRST_CHUNK
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="stream should keep the active request slot while the body is open",
            )
            byte_stream.close()

        sync_streaming_server.release_tail.set()
        assert collect_sync_stream_chunks(response.iter_bytes()) == []
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="closing an unfinished stream should abort the body and release the request slot",
        )


def test_sync_stream_read_timeout_aborts_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    timeout = foghttp.Timeouts(read=READ_TIMEOUT_SECONDS, total=2.0)
    with foghttp.Client() as client:
        with client.stream(
            GET,
            f"{sync_streaming_server.base_url}{SLOW_TAIL_STREAM_PATH}",
            timeout=timeout,
        ) as response:
            byte_stream = response.iter_bytes()
            assert next_sync_stream_chunk(byte_stream) == FIRST_CHUNK
            with pytest.raises(foghttp.ReadTimeout) as exc_info:
                next_sync_stream_chunk(byte_stream)

            assert exc_info.value.phase == "response_body"

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="read timeout should abort the streamed body",
        )


def test_sync_stream_iterator_break_closes_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with foghttp.Client() as client:
        with client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            for chunk in response.iter_bytes():
                assert chunk == FIRST_CHUNK
                break

        sync_streaming_server.release_tail.set()
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="breaking out of byte iteration should close the streamed body",
        )


def test_sync_stream_close_cancels_pending_body_read(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with foghttp.Client() as client:
            with client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}") as response:
                byte_stream = response.iter_bytes()
                assert next_sync_stream_chunk(byte_stream) == FIRST_CHUNK
                pending_chunk = executor.submit(next_sync_stream_chunk, byte_stream)
                wait_for_pending_sync_chunk_future(pending_chunk)

                wait_for_sync_transport_stats(
                    client,
                    lambda stats: stats.active_requests == 1,
                    message="pending streamed body read should keep the active request slot",
                )
                response.close()
                with pytest.raises(foghttp.RequestError, match="stream response body read was aborted"):
                    pending_chunk.result(timeout=STREAM_READ_TIMEOUT)

            sync_streaming_server.release_tail.set()
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
                message="closing a stream with a pending body read should abort it and release resources",
            )
    finally:
        sync_streaming_server.release_tail.set()
        executor.shutdown(wait=False, cancel_futures=True)


def test_sync_client_close_cancels_pending_stream_body_read(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    executor = ThreadPoolExecutor(max_workers=1)
    client = foghttp.Client()
    response: foghttp.StreamResponse | None = None
    try:
        context = client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}")
        response = context.__enter__()
        byte_stream = response.iter_bytes()
        assert next_sync_stream_chunk(byte_stream) == FIRST_CHUNK
        pending_chunk = executor.submit(next_sync_stream_chunk, byte_stream)
        wait_for_pending_sync_chunk_future(pending_chunk)

        client.close()

        with pytest.raises(foghttp.RequestError, match="stream response body read was aborted"):
            pending_chunk.result(timeout=STREAM_READ_TIMEOUT)
    finally:
        sync_streaming_server.release_tail.set()
        if response is not None:
            response.close()
        client.close()
        executor.shutdown(wait=False, cancel_futures=True)


def test_sync_stream_preserves_redirect_history(sync_http_server: str) -> None:
    with (
        foghttp.Client(follow_redirects=True) as client,
        client.stream(GET, f"{sync_http_server}/redirect/{FOUND}") as response,
    ):
        content = b"".join(collect_sync_stream_chunks(response.iter_bytes()))

    assert response.status_code == OK
    assert response.url.endswith("/final")
    assert len(response.history) == 1
    assert response.history[0].status_code == FOUND
    assert content


def test_sync_stream_response_metadata_and_status_helpers(sync_http_server: str) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_http_server}/status/{NOT_FOUND}") as response,
    ):
        assert response.is_client_error
        assert response.is_error
        assert not response.is_success
        assert not response.is_redirect
        assert not response.is_server_error
        assert "StreamResponse" in repr(response)
        with pytest.raises(foghttp.HTTPStatusError) as exc_info:
            response.raise_for_status()

        assert exc_info.value.response is response

        with response as same_response:
            assert same_response is response

        response.close()
        assert collect_sync_stream_chunks(response.iter_bytes()) == []


def test_sync_stream_request_errors_are_mapped(unused_tcp_port: int) -> None:
    connection_refused_url = f"http://127.0.0.1:{unused_tcp_port}"
    with (
        foghttp.Client(timeouts=STREAM_NETWORK_ERROR_TIMEOUTS) as client,
        pytest.raises(foghttp.RequestError),
        client.stream(GET, connection_refused_url),
    ):
        pass
