import threading
import time

import foghttp
from foghttp.methods import GET
from tests.client_streaming.constants import FIRST_CHUNK, GATED_STREAM_PATH, SECOND_CHUNK
from tests.client_streaming.server import SyncStreamingServer

from .constants import (
    GIL_BOUNDARY_SETTLE_DELAY,
    GIL_PROGRESS_WINDOW,
    THREAD_JOIN_TIMEOUT,
    WAIT_TIMEOUT,
)
from .gil_progress import assert_python_thread_progresses
from .thread_worker import run_in_daemon_thread


def test_sync_buffered_request_releases_gil_while_waiting_for_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    def send_buffered_request() -> bytes:
        with foghttp.Client() as client:
            response = client.get(f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}")
        return response.content

    request_result = run_in_daemon_thread(send_buffered_request)
    try:
        if not sync_streaming_server.first_chunk_sent.wait(timeout=WAIT_TIMEOUT):
            msg = "sync server did not send the first chunk"
            raise AssertionError(msg)

        time.sleep(GIL_BOUNDARY_SETTLE_DELAY)
        assert_python_thread_progresses(duration=GIL_PROGRESS_WINDOW)
        if request_result.done():
            msg = "buffered request finished before the gated response tail was released"
            raise AssertionError(msg)

        sync_streaming_server.release_tail.set()
        response_body = request_result.result(timeout=THREAD_JOIN_TIMEOUT)
    finally:
        sync_streaming_server.release_tail.set()

    assert response_body == FIRST_CHUNK + SECOND_CHUNK


def test_sync_stream_body_read_releases_gil_while_waiting_for_chunk(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    second_read_started = threading.Event()

    def read_stream_body() -> list[bytes]:
        with (
            foghttp.Client() as client,
            client.stream(GET, f"{sync_streaming_server.base_url}{GATED_STREAM_PATH}") as response,
        ):
            byte_stream = response.iter_bytes()
            first_chunk = next(byte_stream)
            second_read_started.set()
            second_chunk = next(byte_stream)
            return [first_chunk, second_chunk]

    stream_result = run_in_daemon_thread(read_stream_body)
    try:
        if not sync_streaming_server.first_chunk_sent.wait(timeout=WAIT_TIMEOUT):
            msg = "sync server did not send the first chunk"
            raise AssertionError(msg)
        if not second_read_started.wait(timeout=WAIT_TIMEOUT):
            msg = "sync stream reader did not start the second body read"
            raise AssertionError(msg)

        time.sleep(GIL_BOUNDARY_SETTLE_DELAY)
        assert_python_thread_progresses(duration=GIL_PROGRESS_WINDOW)
        if stream_result.done():
            msg = "stream reader finished before the gated response tail was released"
            raise AssertionError(msg)

        sync_streaming_server.release_tail.set()
        stream_chunks = stream_result.result(timeout=THREAD_JOIN_TIMEOUT)
    finally:
        sync_streaming_server.release_tail.set()

    assert stream_chunks == [FIRST_CHUNK, SECOND_CHUNK]
