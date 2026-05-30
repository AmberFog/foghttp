from contextlib import AsyncExitStack, suppress

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import start_async_streaming_server

from .helpers import wait_for_lifecycle_debug
from .lifecycle_debug_assertions import (
    assert_lifecycle_error_is_actionable,
    assert_url_is_redacted,
)
from .lifecycle_debug_data import sensitive_url
from .lifecycle_debug_predicates import (
    has_no_lifecycle_debug_leaks,
    has_one_stream_request,
)


async def test_async_lifecycle_debug_tracks_stream_until_close() -> None:
    async with AsyncExitStack() as stack:
        server = await stack.enter_async_context(start_async_streaming_server())
        stack.callback(server.release_tail.set)

        async with foghttp.AsyncClient(
            lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
        ) as client:
            async with client.stream(
                GET,
                sensitive_url(server.base_url, stream_constants.GATED_STREAM_PATH),
            ) as response:
                byte_stream = response.aiter_bytes()
                assert await stream_readers.next_stream_chunk(byte_stream) == stream_constants.FIRST_CHUNK

                snapshot = await wait_for_lifecycle_debug(
                    client,
                    has_one_stream_request,
                    message="active stream request was not tracked",
                )
                active_request = snapshot.active_requests[0]
                assert active_request.mode == "stream"
                assert active_request.method == GET
                assert active_request.origin == server.base_url
                assert_url_is_redacted(active_request.redacted_url)

                await response.aclose()

            snapshot = await wait_for_lifecycle_debug(
                client,
                has_no_lifecycle_debug_leaks,
                message="closed stream request was not released",
            )
            assert snapshot.active_request_count == 0
            client.assert_no_lifecycle_leaks()


async def test_async_lifecycle_debug_strict_aclose_reports_active_stream_request() -> None:
    async with AsyncExitStack() as stack:
        server = await stack.enter_async_context(start_async_streaming_server())
        stack.callback(server.release_tail.set)
        client = foghttp.AsyncClient(
            lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
        )

        try:
            async with client.stream(
                GET,
                sensitive_url(server.base_url, stream_constants.GATED_STREAM_PATH),
            ) as response:
                byte_stream = response.aiter_bytes()
                assert await stream_readers.next_stream_chunk(byte_stream) == stream_constants.FIRST_CHUNK

                await wait_for_lifecycle_debug(
                    client,
                    has_one_stream_request,
                    message="active stream request was not tracked before strict close",
                )

                with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
                    await client.aclose()
                message = str(exc_info.value)
                assert_lifecycle_error_is_actionable(message)
                assert "stream" in message
                assert_url_is_redacted(message)
        finally:
            server.release_tail.set()
            with suppress(foghttp.LifecycleError):
                await client.aclose()

        snapshot = client.dump_lifecycle_debug()
        assert snapshot.closed is True
        assert snapshot.active_request_count == 0


async def test_async_lifecycle_debug_releases_stream_at_eof() -> None:
    async with AsyncExitStack() as stack:
        server = await stack.enter_async_context(start_async_streaming_server())
        stack.callback(server.release_tail.set)

        async with foghttp.AsyncClient(
            lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
        ) as client:
            async with client.stream(
                GET,
                server.base_url + stream_constants.GATED_STREAM_PATH,
            ) as response:
                byte_stream = response.aiter_bytes()
                assert await stream_readers.next_stream_chunk(byte_stream) == stream_constants.FIRST_CHUNK

                await wait_for_lifecycle_debug(
                    client,
                    has_one_stream_request,
                    message="active stream request was not tracked before EOF",
                )

                server.release_tail.set()
                assert await stream_readers.collect_stream_chunks(byte_stream) == [
                    stream_constants.SECOND_CHUNK,
                ]

            snapshot = await wait_for_lifecycle_debug(
                client,
                has_no_lifecycle_debug_leaks,
                message="EOF stream request was not released",
            )
            assert snapshot.active_request_count == 0
            client.assert_no_lifecycle_leaks()
