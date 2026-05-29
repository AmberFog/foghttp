import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress
import gc

import pytest

import foghttp
from foghttp._client.lifecycle_debug import AsyncLifecycleDebugTracker
from foghttp.methods import GET
from tests.client_streaming import (
    constants as stream_constants,
    stream_readers,
)
from tests.client_streaming.server import start_async_streaming_server

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug, wait_for_no_active_requests


_BLOCKER_AND_WAITER_DEBUG_REQUESTS = 2
_DEBUG_REQUEST_MESSAGE_CAP = 10
_CAPPED_DEBUG_REQUEST_COUNT = _DEBUG_REQUEST_MESSAGE_CAP + 1
_QUERY_REDACTED_VALUE_ONE = "debug-query-value-one"
_QUERY_REDACTED_VALUE_TWO = "debug-query-value-two"
_USERINFO_REDACTED_VALUE = "debug-userinfo-value"
_SENSITIVE_USERNAME = "debug-user"
_VISIBLE_QUERY_VALUE = "visible-value"


class _ContextBodyError(Exception):
    pass


async def test_async_lifecycle_debug_tracks_active_buffered_request(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        task = asyncio.create_task(
            client.get(_sensitive_url(cancellation_server, SLOW_HEADERS_PATH)),
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
            _assert_url_is_redacted(active_request.redacted_url)
            assert active_request.age_ns >= 0
            with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
                client.assert_no_lifecycle_leaks()
            _assert_lifecycle_error_is_actionable(str(exc_info.value))
            _assert_url_is_redacted(str(exc_info.value))
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


async def test_async_lifecycle_assertion_reports_transport_pressure_without_debug(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        try:
            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_disabled_transport_pressure,
                message="transport pressure was not visible without debug handles",
            )
            assert snapshot.enabled is False
            assert snapshot.active_request_count == 0

            with pytest.raises(foghttp.LifecycleError, match="active_async_requests=0") as exc_info:
                client.assert_no_lifecycle_leaks()
            assert "transport_active_requests=1" in str(exc_info.value)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

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
                _sensitive_url(server.base_url, stream_constants.GATED_STREAM_PATH),
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
                _assert_url_is_redacted(active_request.redacted_url)

                await response.aclose()

            snapshot = await wait_for_lifecycle_debug(
                client,
                _has_no_lifecycle_debug_leaks,
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
                _sensitive_url(server.base_url, stream_constants.GATED_STREAM_PATH),
            ) as response:
                byte_stream = response.aiter_bytes()
                assert await stream_readers.next_stream_chunk(byte_stream) == stream_constants.FIRST_CHUNK

                await wait_for_lifecycle_debug(
                    client,
                    _has_one_stream_request,
                    message="active stream request was not tracked before strict close",
                )

                with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
                    await client.aclose()
                message = str(exc_info.value)
                _assert_lifecycle_error_is_actionable(message)
                assert "stream" in message
                _assert_url_is_redacted(message)
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


async def test_async_lifecycle_debug_strict_context_exit_preserves_body_exception(
    cancellation_server: str,
) -> None:
    client = foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
    )
    tasks: list[asyncio.Task[foghttp.Response]] = []

    try:
        with pytest.raises(_ContextBodyError):
            await _raise_context_body_error_with_active_request(
                client,
                cancellation_server,
                tasks,
            )
    finally:
        for task in tasks:
            with pytest.raises(asyncio.CancelledError):
                await task

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.closed is True
    assert snapshot.active_request_count == 0


async def test_async_lifecycle_debug_strict_aclose_reports_active_request(
    cancellation_server: str,
) -> None:
    client = foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
    )
    task = asyncio.create_task(client.get(_sensitive_url(cancellation_server, SLOW_HEADERS_PATH)))
    await wait_for_lifecycle_debug(
        client,
        _has_one_buffered_request,
        message="active request was not tracked before strict close",
    )

    with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
        await client.aclose()
    _assert_lifecycle_error_is_actionable(str(exc_info.value))
    _assert_url_is_redacted(str(exc_info.value))
    with pytest.raises(asyncio.CancelledError):
        await task

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.closed is True
    assert snapshot.active_request_count == 0


async def test_async_lifecycle_debug_leak_message_caps_active_request_details(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        tasks = [
            asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
            for _request_index in range(_CAPPED_DEBUG_REQUEST_COUNT)
        ]
        try:
            await wait_for_lifecycle_debug(
                client,
                _has_debug_request_count(_CAPPED_DEBUG_REQUEST_COUNT),
                message="active request cap scenario was not reached",
            )

            with pytest.raises(foghttp.LifecycleError) as exc_info:
                client.assert_no_lifecycle_leaks()
            message = str(exc_info.value)
            assert f"active_async_requests={_CAPPED_DEBUG_REQUEST_COUNT}" in message
            assert "omitted_active_requests=1" in message
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with pytest.raises(asyncio.CancelledError):
                    await task

        await wait_for_no_active_requests(client)


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


def test_async_lifecycle_debug_unclosed_warning_redacts_and_caps_active_request_context() -> None:
    tracker = AsyncLifecycleDebugTracker(foghttp.AsyncLifecycleDebugConfig())
    for request_index in range(_CAPPED_DEBUG_REQUEST_COUNT):
        tracker.start_request(
            foghttp.Request(
                GET,
                _sensitive_url("http://example.com", f"/requests/{request_index}"),
            ),
            mode="buffered",
        )

    message = tracker.unclosed_warning_message("unclosed")

    assert f"active_async_requests={_CAPPED_DEBUG_REQUEST_COUNT}" in message
    assert "omitted_active_requests=1" in message
    _assert_url_is_redacted(message)


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


def _has_disabled_transport_pressure(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
    return not snapshot.enabled and snapshot.active_request_count == 0 and snapshot.transport_active_requests == 1


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


def _has_debug_request_count(
    expected_request_count: int,
) -> Callable[[foghttp.AsyncLifecycleDebugSnapshot], bool]:
    def condition(snapshot: foghttp.AsyncLifecycleDebugSnapshot) -> bool:
        return (
            snapshot.active_request_count == expected_request_count
            and snapshot.transport_active_requests == expected_request_count
        )

    return condition


def _sensitive_url(base_url: str, path: str) -> str:
    scheme, authority = base_url.split("://", maxsplit=1)
    return (
        f"{scheme}://{_SENSITIVE_USERNAME}:{_USERINFO_REDACTED_VALUE}@{authority}{path}"
        f"?token={_QUERY_REDACTED_VALUE_ONE}&api_key={_QUERY_REDACTED_VALUE_TWO}&safe={_VISIBLE_QUERY_VALUE}"
    )


def _assert_url_is_redacted(value: str) -> None:
    assert _SENSITIVE_USERNAME not in value
    assert _USERINFO_REDACTED_VALUE not in value
    assert _QUERY_REDACTED_VALUE_ONE not in value
    assert _QUERY_REDACTED_VALUE_TWO not in value
    assert f"safe={_VISIBLE_QUERY_VALUE}" in value
    assert "<redacted>" in value


def _assert_lifecycle_error_is_actionable(message: str) -> None:
    assert "active_requests=(" in message
    assert "1:GET" in message
    assert "age_ms=" in message
    assert "omitted_active_requests=0" in message


async def _raise_context_body_error_with_active_request(
    client: foghttp.AsyncClient,
    cancellation_server: str,
    tasks: list[asyncio.Task[foghttp.Response]],
) -> None:
    async with client:
        tasks.append(asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH)))
        await wait_for_lifecycle_debug(
            client,
            _has_one_buffered_request,
            message="active request was not tracked before context body error",
        )
        raise _ContextBodyError


def _drop_client(client_holder: list[foghttp.AsyncClient]) -> None:
    client_holder.clear()
    gc.collect()
