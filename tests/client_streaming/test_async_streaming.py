import asyncio

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.client_streaming.constants import (
    ENTER_STREAM_TIMEOUT,
    FIRST_CHUNK,
    GATED_STREAM_PATH,
    READ_TIMEOUT_SECONDS,
    SECOND_CHUNK,
    SLOW_TAIL_STREAM_PATH,
    STREAM_NETWORK_ERROR_TIMEOUTS,
    STREAM_READ_TIMEOUT,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_streaming.stream_readers import (
    collect_stream_chunks,
    next_stream_chunk,
    wait_for_pending_chunk_task,
)
from tests.support.transport_stats import wait_for_async_transport_stats


async def _close_stream_from_cancelled_task(response: foghttp.AsyncStreamResponse) -> None:
    current_task = asyncio.current_task()
    assert current_task is not None
    current_task.cancel()
    await response.aclose()


async def test_stream_enters_after_headers_without_buffering_tail(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        context = client.stream(GET, f"{streaming_server.base_url}{GATED_STREAM_PATH}")
        response = await asyncio.wait_for(context.__aenter__(), timeout=ENTER_STREAM_TIMEOUT)
        try:
            assert response.status_code == OK
            response.raise_for_status()
            assert not streaming_server.release_tail.is_set()

            byte_stream = response.aiter_bytes()
            first = await next_stream_chunk(byte_stream)
            assert first == FIRST_CHUNK
            assert not streaming_server.release_tail.is_set()

            streaming_server.release_tail.set()
            remaining = await collect_stream_chunks(byte_stream)
            assert [first, *remaining] == [FIRST_CHUNK, SECOND_CHUNK]
        finally:
            await context.__aexit__(None, None, None)

        assert client.stats().failed_requests == 0
        assert client.stats().response_body_closed == 1


async def test_stream_context_abort_releases_active_request_slot(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, f"{streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            byte_stream = response.aiter_bytes()
            assert await next_stream_chunk(byte_stream) == FIRST_CHUNK
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="stream should keep the active request slot while the body is open",
            )
            await byte_stream.aclose()

        streaming_server.release_tail.set()
        assert await collect_stream_chunks(response.aiter_bytes()) == []
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="closing an unfinished stream should abort the body and release the request slot",
        )


async def test_stream_read_timeout_aborts_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    timeout = foghttp.Timeouts(read=READ_TIMEOUT_SECONDS, total=2.0)
    async with foghttp.AsyncClient() as client:
        async with client.stream(
            GET,
            f"{streaming_server.base_url}{SLOW_TAIL_STREAM_PATH}",
            timeout=timeout,
        ) as response:
            byte_stream = response.aiter_bytes()
            assert await next_stream_chunk(byte_stream) == FIRST_CHUNK
            with pytest.raises(foghttp.ReadTimeout) as exc_info:
                await next_stream_chunk(byte_stream)

            assert exc_info.value.phase == "response_body"

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="read timeout should abort the streamed body",
        )


async def test_stream_iterator_break_closes_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, f"{streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            async for chunk in response.aiter_bytes():
                assert chunk == FIRST_CHUNK
                break

        streaming_server.release_tail.set()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="breaking out of byte iteration should close the streamed body",
        )


async def test_stream_aclose_cancels_pending_body_read(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, f"{streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            byte_stream = response.aiter_bytes()
            assert await next_stream_chunk(byte_stream) == FIRST_CHUNK
            pending_chunk = asyncio.create_task(anext(byte_stream))
            await wait_for_pending_chunk_task(pending_chunk)

            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="pending streamed body read should keep the active request slot",
            )
            await response.aclose()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending_chunk, timeout=STREAM_READ_TIMEOUT)

        streaming_server.release_tail.set()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="closing a stream with a pending body read should cancel it and release resources",
        )


async def test_stream_aclose_releases_slot_when_close_task_is_already_cancelled(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, f"{streaming_server.base_url}{GATED_STREAM_PATH}") as response:
            byte_stream = response.aiter_bytes()
            assert await next_stream_chunk(byte_stream) == FIRST_CHUNK
            close_task = asyncio.create_task(_close_stream_from_cancelled_task(response))

            with pytest.raises(asyncio.CancelledError):
                await close_task

        streaming_server.release_tail.set()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="stream close should release resources even when the close task is already cancelled",
        )


async def test_stream_preserves_redirect_history(http_server: str) -> None:
    async with (
        foghttp.AsyncClient(follow_redirects=True) as client,
        client.stream(GET, f"{http_server}/redirect/{FOUND}") as response,
    ):
        content = b"".join(await collect_stream_chunks(response.aiter_bytes()))

    assert response.status_code == OK
    assert response.url.endswith("/final")
    assert len(response.history) == 1
    assert response.history[0].status_code == FOUND
    assert content


async def test_stream_response_metadata_and_status_helpers(http_server: str) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{http_server}/status/{NOT_FOUND}") as response,
    ):
        assert response.is_client_error
        assert response.is_error
        assert not response.is_success
        assert not response.is_redirect
        assert not response.is_server_error
        assert "AsyncStreamResponse" in repr(response)
        with pytest.raises(foghttp.HTTPStatusError) as exc_info:
            response.raise_for_status()

        assert exc_info.value.response is response

        async with response as same_response:
            assert same_response is response

        await response.aclose()
        assert await collect_stream_chunks(response.aiter_bytes()) == []


async def test_stream_request_errors_are_mapped(unused_tcp_port: int) -> None:
    connection_refused_url = f"http://127.0.0.1:{unused_tcp_port}"
    async with foghttp.AsyncClient(timeouts=STREAM_NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError):
            async with client.stream(GET, connection_refused_url):
                pass
