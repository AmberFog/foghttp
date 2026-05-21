import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_RESPONSE_PATH
from .helpers import wait_for_async_stats


EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE = 2


async def test_dump_transport_state_reports_active_and_pending_pressure(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        blocker = asyncio.create_task(client.get(resource_http_server + SLOW_RESPONSE_PATH))
        waiter: asyncio.Task[foghttp.Response] | None = None
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_requests == 1)

            waiter = asyncio.create_task(client.get(resource_http_server))
            await wait_for_async_stats(client, lambda stats: stats.pending_requests == 1)

            state = client.dump_transport_state()
            origin_pressure = state["origins"][resource_http_server]

            blocker_response = await blocker
            waiter_response = await waiter
            final_state = client.dump_transport_state()
        finally:
            for task in (blocker, waiter):
                if task is not None and not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task

    assert blocker_response.status_code == OK
    assert waiter_response.status_code == OK
    assert state["active_requests"] == 1
    assert state["pending_requests"] == 1
    assert state["pool_acquire_attempts"] == EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE
    assert state["pool_acquire_immediate"] == 1
    assert state["pool_acquire_waited"] == 1
    assert state["pool_acquire_timeouts"] == 0
    assert set(state["origins"]) == {resource_http_server}
    assert origin_pressure["active_requests"] == 1
    assert origin_pressure["pending_requests"] == 1
    assert origin_pressure["pool_acquire_attempts"] == EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE
    assert origin_pressure["pool_acquire_immediate"] == 1
    assert origin_pressure["pool_acquire_waited"] == 1
    assert origin_pressure["pool_acquire_timeouts"] == 0
    assert origin_pressure["last_activity_at_ns"] > 0
    assert final_state["active_requests"] == 0
    assert final_state["pending_requests"] == 0
    assert final_state["origins"][resource_http_server]["active_requests"] == 0
    assert final_state["origins"][resource_http_server]["pending_requests"] == 0
