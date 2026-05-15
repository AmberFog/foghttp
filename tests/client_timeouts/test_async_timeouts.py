import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import (
    EXPECTED_REQUESTS_AFTER_POOL_WAIT_RECOVERY,
    RECOVERY_TOTAL_TIMEOUT,
    SLOW_RESPONSE_PATH,
    TOTAL_TIMEOUT,
)
from .helpers import (
    assert_timeout_error_stats,
    assert_timeout_recovery_stats,
    wait_for_async_stats,
)


async def test_async_total_timeout_maps_to_generic_timeout_and_client_recovers(
    timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(timeout_http_server + SLOW_RESPONSE_PATH)

        stats_after_error = client.stats()
        response = await client.get(
            timeout_http_server,
            timeout=foghttp.Timeouts(total=RECOVERY_TOTAL_TIMEOUT),
        )
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert_timeout_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_timeout_recovery_stats(final_stats)


async def test_async_total_timeout_wins_over_longer_pool_timeout(
    timeout_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)
    default_timeouts = foghttp.Timeouts(pool=1.0, total=RECOVERY_TOTAL_TIMEOUT)
    waiting_timeouts = foghttp.Timeouts(pool=1.0, total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(limits=limits, timeouts=default_timeouts) as client:
        blocker = asyncio.create_task(client.get(timeout_http_server + SLOW_RESPONSE_PATH))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_requests == 1)

            with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
                await client.get(timeout_http_server, timeout=waiting_timeouts)

            stats_after_error = client.stats()
            blocker_response = await blocker
            recovery_response = await client.get(timeout_http_server)
            final_stats = client.stats()
        finally:
            if not blocker.done():
                blocker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await blocker

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert stats_after_error.active_requests == 1
    assert stats_after_error.pending_requests == 0
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.pool_acquire_timeouts == 0
    assert blocker_response.status_code == OK
    assert recovery_response.status_code == OK
    assert final_stats.total_requests == EXPECTED_REQUESTS_AFTER_POOL_WAIT_RECOVERY
    assert final_stats.failed_requests == 1
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0
    assert final_stats.pool_acquire_timeouts == 0
