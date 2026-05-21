import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import (
    NO_POOL_BLOCK,
    PER_ORIGIN_ACTIVE_REQUESTS_BLOCK,
    SLOW_RESPONSE_PATH,
)
from .helpers import wait_for_async_stats


async def test_dump_pool_diagnostics_reports_per_origin_pressure_and_clears_cancelled_waiter(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_active_requests_per_origin=1,
        max_pending_requests=1,
    )
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        blocker = asyncio.create_task(client.get(resource_http_server + SLOW_RESPONSE_PATH))
        waiter = None
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_requests == 1)

            waiter = asyncio.create_task(client.get(resource_http_server))
            await wait_for_async_stats(client, lambda stats: stats.pending_requests == 1)

            diagnostics = client.dump_pool_diagnostics()
            origin_diagnostics = diagnostics["origins"][resource_http_server]

            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            await wait_for_async_stats(
                client,
                lambda stats: stats.active_requests == 1 and stats.pending_requests == 0,
            )
            cancelled_diagnostics = client.dump_pool_diagnostics()

            blocker_response = await blocker
        finally:
            if waiter is not None and not waiter.done():
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
            if not blocker.done():
                blocker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await blocker

    assert blocker_response.status_code == OK
    assert diagnostics["active_requests"] == 1
    assert diagnostics["pending_requests"] == 1
    assert diagnostics["max_active_requests"] == limits.max_active_requests
    assert diagnostics["max_active_requests_per_origin"] == limits.max_active_requests_per_origin
    assert diagnostics["max_pending_requests"] == limits.max_pending_requests
    assert diagnostics["pending_queue_full"] is True
    assert diagnostics["blocked_by"] == PER_ORIGIN_ACTIVE_REQUESTS_BLOCK
    assert diagnostics["oldest_pending_request_wait_ns"] > 0
    assert origin_diagnostics["active_requests"] == 1
    assert origin_diagnostics["pending_requests"] == 1
    assert origin_diagnostics["blocked_by"] == PER_ORIGIN_ACTIVE_REQUESTS_BLOCK
    assert origin_diagnostics["oldest_pending_request_wait_ns"] > 0
    assert origin_diagnostics["pool_acquire_timeouts"] == 0
    assert cancelled_diagnostics["pending_requests"] == 0
    assert cancelled_diagnostics["oldest_pending_request_wait_ns"] == 0
    assert cancelled_diagnostics["blocked_by"] == NO_POOL_BLOCK
    cancelled_origin_diagnostics = cancelled_diagnostics["origins"][resource_http_server]
    assert cancelled_origin_diagnostics["pending_requests"] == 0
    assert cancelled_origin_diagnostics["oldest_pending_request_wait_ns"] == 0
    assert cancelled_origin_diagnostics["blocked_by"] == NO_POOL_BLOCK
