import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_BODY_PATH, SLOW_HEADERS_PATH
from .helpers import wait_for_no_active_requests, wait_for_transport_state


BLOCKER_AND_WAITER_ATTEMPTS = 2
BLOCKER_AND_RECOVERY_IMMEDIATE_ACQUIRES = 2
BLOCKER_WAITER_AND_RECOVERY_ATTEMPTS = 3


async def test_cancelled_async_request_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_asyncio_timeout_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await client.get(cancellation_server + SLOW_HEADERS_PATH)

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_cancelled_async_request_during_slow_body_aborts_rust_request(cancellation_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_BODY_PATH))
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)

    assert response.status_code == OK
    assert response.content == b"OK"


async def test_aclose_cancels_in_flight_async_request(cancellation_server: str) -> None:
    client = foghttp.AsyncClient()
    task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
    await asyncio.sleep(0.05)

    await client.aclose()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)


async def test_cancelled_async_request_waiting_for_transport_slot_releases_pending_request(
    cancellation_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)

    async with foghttp.AsyncClient(limits=limits) as client:
        blocker = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        waiter = None
        try:
            await asyncio.sleep(0.05)
            waiter = asyncio.create_task(client.get(cancellation_server))
            await wait_for_transport_state(
                client,
                active_requests=1,
                pending_requests=1,
            )

            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter

            await wait_for_transport_state(
                client,
                active_requests=1,
                pending_requests=0,
            )
            stats_after_cancellation = client.stats()
        finally:
            if waiter is not None and not waiter.done():
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
            if not blocker.done():
                blocker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await blocker

        await wait_for_no_active_requests(client)
        response = await client.get(cancellation_server)
        final_stats = client.stats()

    assert response.status_code == OK
    assert response.content == b"OK"
    assert stats_after_cancellation.peak_pending_requests == 1
    assert stats_after_cancellation.pool_acquire_attempts == BLOCKER_AND_WAITER_ATTEMPTS
    assert stats_after_cancellation.pool_acquire_immediate == 1
    assert stats_after_cancellation.pool_acquire_waited == 1
    assert stats_after_cancellation.pool_acquire_timeouts == 0
    assert stats_after_cancellation.pool_acquire_wait_time_last_ns > 0
    assert final_stats.pool_acquire_attempts == BLOCKER_WAITER_AND_RECOVERY_ATTEMPTS
    assert final_stats.pool_acquire_immediate == BLOCKER_AND_RECOVERY_IMMEDIATE_ACQUIRES
    assert final_stats.pool_acquire_waited == 1
