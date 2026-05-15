import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .helpers import wait_for_async_stats


async def test_pending_request_queue_full(resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full"):
            await client.get(resource_http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


async def test_zero_pending_queue_allows_available_request_slot(resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=0)

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(resource_http_server)

        assert response.status_code == OK
        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 0
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 0


async def test_pool_acquire_timeout(resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
            await client.get(resource_http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


async def test_pending_requests_are_tracked_while_waiting(resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.2)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        task = asyncio.create_task(client.get(resource_http_server))
        try:
            await wait_for_async_stats(
                client,
                lambda stats: stats.pending_requests == 1 and stats.active_requests == 0,
            )

            stats = client.stats()
            assert stats.pending_requests == 1
            assert stats.active_requests == 0
            with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
                await task
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1
