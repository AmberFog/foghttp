import asyncio

import pytest

import foghttp
from foghttp.methods import GET

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug, wait_for_no_active_requests
from .lifecycle_debug_assertions import (
    assert_lifecycle_error_is_actionable,
    assert_url_is_redacted,
)
from .lifecycle_debug_data import (
    BLOCKER_AND_WAITER_DEBUG_REQUESTS,
    sensitive_url,
)
from .lifecycle_debug_predicates import (
    has_cancelled_pending_waiter,
    has_disabled_transport_pressure,
    has_one_active_transport_request,
    has_one_buffered_request,
    has_one_pending_transport_request,
)


async def test_async_lifecycle_debug_tracks_active_buffered_request(
    cancellation_server: str,
) -> None:
    async with foghttp.AsyncClient(
        lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
    ) as client:
        task = asyncio.create_task(
            client.get(sensitive_url(cancellation_server, SLOW_HEADERS_PATH)),
        )
        try:
            snapshot = await wait_for_lifecycle_debug(
                client,
                has_one_buffered_request,
                message="active buffered request was not tracked",
            )

            active_request = snapshot.active_requests[0]
            assert active_request.method == GET
            assert active_request.origin == cancellation_server
            assert_url_is_redacted(active_request.redacted_url)
            assert active_request.age_ns >= 0
            with pytest.raises(foghttp.LifecycleError, match="active_async_requests=1") as exc_info:
                client.assert_no_lifecycle_leaks()
            assert_lifecycle_error_is_actionable(str(exc_info.value))
            assert_url_is_redacted(str(exc_info.value))
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
                has_one_active_transport_request,
                message="blocking request was not tracked",
            )
            waiter = asyncio.create_task(client.get(cancellation_server))

            snapshot = await wait_for_lifecycle_debug(
                client,
                has_one_pending_transport_request,
                message="pending acquire waiter was not tracked",
            )
            assert snapshot.active_request_count == BLOCKER_AND_WAITER_DEBUG_REQUESTS

            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter

            snapshot = await wait_for_lifecycle_debug(
                client,
                has_cancelled_pending_waiter,
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
                has_disabled_transport_pressure,
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
