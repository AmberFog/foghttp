import asyncio
from contextlib import AsyncExitStack
import gc

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import start_async_streaming_server

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug, wait_for_no_active_requests


_BLOCKER_AND_WAITER_DEBUG_REQUESTS = 2


async def test_async_lifecycle_debug_tracks_active_buffered_request(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        task = asyncio.create_task(
            client.get(f"{cancellation_server}{SLOW_HEADERS_PATH}?token=secret"),
        )
        try:
            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_one_buffered_request,
                message="active buffered request was not tracked",
            )

            active_request = snapshot.active_requests[0]
            assert active_request.method == GET
            assert active_request.origin == cancellation_server
            assert "secret" not in active_request.redacted_url
            assert active_request.age_ns >= 0
            with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1"):
                client.assert_no_lifecycle_leaks()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        await wait_for_no_active_requests(client)
        client.assert_no_lifecycle_leaks()


async def test_async_lifecycle_debug_reports_pending_acquire_after_cancellation(
    cancellation_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)

    async with foghttp.AsyncClient(
        limits=limits,
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        blocker = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        waiter = None
        try:
            await wait_for_lifecycle_debug(
                client,
                _has_one_active_transport_request,
                message="blocking request was not tracked",
            )
            waiter = asyncio.create_task(client.get(cancellation_server))

            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_one_pending_transport_request,
                message="pending acquire waiter was not tracked",
            )
            assert snapshot.active_request_count == _BLOCKER_AND_WAITER_DEBUG_REQUESTS

            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter

            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_cancelled_pending_waiter,
                message="cancelled pending waiter was not released",
            )
            assert snapshot.active_request_count == 1
        finally:
            if waiter is not None and not waiter.done():
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
            blocker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await blocker

        await wait_for_no_active_requests(client)
        client.assert_no_lifecycle_leaks()


async def test_async_lifecycle_debug_tracks_stream_until_close() -> None:
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

                snapshot = await wait_for_lifecycle_debug(
                    client,
                    _has_one_stream_request,
                    message="active stream request was not tracked",
                )
                active_request = snapshot.active_requests[0]
                assert active_request.mode == "stream"
                assert active_request.method == GET
                assert active_request.origin == server.base_url

                await response.aclose()

            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_no_lifecycle_debug_leaks,
                message="closed stream request was not released",
            )
            assert snapshot.active_request_count == 0
            client.assert_no_lifecycle_leaks()


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
                    _has_one_stream_request,
                    message="active stream request was not tracked before EOF",
                )

                server.release_tail.set()
                assert await stream_readers.collect_stream_chunks(byte_stream) == [
                    stream_constants.SECOND_CHUNK,
                ]

            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_no_lifecycle_debug_leaks,
                message="EOF stream request was not released",
            )
            assert snapshot.active_request_count == 0
            client.assert_no_lifecycle_leaks()


async def test_async_lifecycle_debug_strict_aclose_reports_active_request(
    cancellation_server: str,
) -> None:
    client = foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
    )
    task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
    await wait_for_lifecycle_debug(
        client,
        _has_one_buffered_request,
        message="active request was not tracked before strict close",
    )

    with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1"):
        await client.aclose()
    with pytest.raises(asyncio.CancelledError):
        await task

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.closed is True
    assert snapshot.active_request_count == 0


def test_async_lifecycle_debug_unclosed_warning_includes_debug_context() -> None:
    client_holder = [
        foghttp.AsyncClient(
            lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
        ),
    ]

    with pytest.warns(
        foghttp.UnclosedClientError,
        match="lifecycle_debug_enabled=True; active_async_requests=0",
    ):
        _drop_client(client_holder)


def _has_one_buffered_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.enabled
        and snapshot.active_request_count == 1
        and snapshot.active_requests[0].mode == "buffered"
        and snapshot.transport_active_requests == 1
    )


def _has_one_stream_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.enabled
        and snapshot.active_request_count == 1
        and snapshot.active_requests[0].mode == "stream"
        and snapshot.transport_active_requests == 1
    )


def _has_no_lifecycle_debug_leaks(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return (
        snapshot.active_request_count == 0
        and snapshot.transport_active_requests == 0
        and snapshot.transport_pending_requests == 0
    )


def _has_one_active_transport_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.active_request_count == 1 and snapshot.transport_active_requests == 1


def _has_one_pending_transport_request(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.transport_active_requests == 1 and snapshot.transport_pending_requests == 1


def _has_cancelled_pending_waiter(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return snapshot.transport_active_requests == 1 and snapshot.transport_pending_requests == 0


def _drop_client(client_holder: list[foghttp.AsyncClient]) -> None:
    client_holder.clear()
    gc.collect()
