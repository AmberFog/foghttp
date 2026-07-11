import asyncio
import os

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming.constants import FIRST_CHUNK, GATED_STREAM_PATH, SECOND_CHUNK
from tests.client_streaming.server import SyncStreamingServer

from .fork_actions import (
    ForkResult,
    open_async_stream_response,
    read_async_stream_body,
    read_next_async_stream_chunk,
    run_in_fork,
)


pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork is unavailable")


def test_stream_response_rejects_stale_process_owner_and_closes_wrapper_copy(
    sync_fork_streaming_server: SyncStreamingServer,
) -> None:
    url = f"{sync_fork_streaming_server.base_url}{GATED_STREAM_PATH}"
    with foghttp.Client() as client:
        response = client.stream(GET, url).__enter__()
        try:
            assert sync_fork_streaming_server.first_chunk_sent.wait(timeout=1.0)
            response._process_id = -1  # noqa: SLF001 - simulate inherited ownership deterministically.

            with pytest.raises(foghttp.LifecycleError, match="cannot be used in forked process"):
                next(response.iter_bytes())
        finally:
            response.close()
            sync_fork_streaming_server.release_tail.set()


def test_inherited_open_sync_stream_after_fork_raises_without_touching_parent(
    sync_fork_streaming_server: SyncStreamingServer,
) -> None:
    url = f"{sync_fork_streaming_server.base_url}{GATED_STREAM_PATH}"
    with foghttp.Client() as client, client.stream(GET, url) as response:
        assert sync_fork_streaming_server.first_chunk_sent.wait(timeout=1.0)

        result = run_in_fork(lambda: next(response.iter_bytes()))

        _assert_stream_fork_error(result)
        close_result = run_in_fork(response.close)
        assert close_result.ok is True
        assert close_result.exit_status == 0
        sync_fork_streaming_server.release_tail.set()
        assert b"".join(response.iter_bytes()) == FIRST_CHUNK + SECOND_CHUNK


def test_inherited_open_async_stream_after_fork_raises_without_touching_parent(
    sync_fork_streaming_server: SyncStreamingServer,
) -> None:
    url = f"{sync_fork_streaming_server.base_url}{GATED_STREAM_PATH}"
    client = foghttp.AsyncClient()
    response = open_async_stream_response(client, url)
    try:
        assert sync_fork_streaming_server.first_chunk_sent.wait(timeout=1.0)

        result = run_in_fork(lambda: read_next_async_stream_chunk(response))

        _assert_stream_fork_error(result)
        close_result = run_in_fork(lambda: asyncio.run(response.aclose()))
        assert close_result.ok is True
        assert close_result.exit_status == 0
        sync_fork_streaming_server.release_tail.set()
        assert read_async_stream_body(response) == FIRST_CHUNK + SECOND_CHUNK
    finally:
        sync_fork_streaming_server.release_tail.set()
        asyncio.run(response.aclose())
        asyncio.run(client.aclose())


def _assert_stream_fork_error(result: ForkResult) -> None:
    assert result.ok is False
    assert result.error_type == "LifecycleError"
    assert "FogHTTP stream response was created" in result.message
    assert "cannot be used in forked process" in result.message
