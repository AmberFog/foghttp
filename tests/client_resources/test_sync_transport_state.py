from concurrent.futures import ThreadPoolExecutor

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_RESPONSE_PATH
from .helpers import wait_for_sync_stats


EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE = 2


def test_dump_transport_state_reports_active_and_pending_pressure(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    with (
        foghttp.Client(limits=limits, timeouts=timeouts) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        blocker = executor.submit(
            client.get,
            sync_resource_http_server + SLOW_RESPONSE_PATH,
        )
        wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)

        waiter = executor.submit(client.get, sync_resource_http_server)
        wait_for_sync_stats(client, lambda stats: stats.pending_requests == 1)

        state = client.dump_transport_state()
        origin_pressure = state["origins"][sync_resource_http_server]

        blocker_response = blocker.result(timeout=1)
        waiter_response = waiter.result(timeout=1)
        final_state = client.dump_transport_state()

    assert blocker_response.status_code == OK
    assert waiter_response.status_code == OK
    assert state["active_requests"] == 1
    assert state["pending_requests"] == 1
    assert state["pool_acquire_attempts"] == EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE
    assert state["pool_acquire_immediate"] == 1
    assert state["pool_acquire_waited"] == 1
    assert state["pool_acquire_timeouts"] == 0
    assert set(state["origins"]) == {sync_resource_http_server}
    assert origin_pressure["active_requests"] == 1
    assert origin_pressure["pending_requests"] == 1
    assert origin_pressure["pool_acquire_attempts"] == EXPECTED_ACQUIRE_ATTEMPTS_UNDER_PRESSURE
    assert origin_pressure["pool_acquire_immediate"] == 1
    assert origin_pressure["pool_acquire_waited"] == 1
    assert origin_pressure["pool_acquire_timeouts"] == 0
    assert origin_pressure["last_activity_at_ns"] > 0
    assert final_state["active_requests"] == 0
    assert final_state["pending_requests"] == 0
    assert final_state["origins"][sync_resource_http_server]["active_requests"] == 0
    assert final_state["origins"][sync_resource_http_server]["pending_requests"] == 0
