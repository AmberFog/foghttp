from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.redirect_helpers import redirect_to_location_url

from .constants import SLOW_RESPONSE_PATH
from .helpers import wait_for_sync_stats


EXPECTED_COMPLETED_REQUESTS = 2
EXPECTED_ORIGIN_ATTEMPTS_UNDER_PRESSURE = 2


def test_same_origin_requests_wait_for_per_origin_slot(sync_resource_http_server: str) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_active_requests_per_origin=1,
        max_pending_requests=1,
    )
    timeouts = foghttp.Timeouts(pool=0.05, total=1.0)

    with (
        foghttp.Client(limits=limits, timeouts=timeouts) as client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        blocker = executor.submit(
            client.get,
            sync_resource_http_server + SLOW_RESPONSE_PATH,
        )
        wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)

        with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
            client.get(sync_resource_http_server)

        stats = client.stats()
        state = client.dump_transport_state()
        origin_pressure = state["origins"][sync_resource_http_server]
        assert stats.active_requests == 1
        assert stats.pending_requests == 0
        assert stats.failed_requests == 1
        assert stats.pool_acquire_timeouts == 1
        assert origin_pressure["active_requests"] == 1
        assert origin_pressure["pending_requests"] == 0
        assert origin_pressure["peak_pending_requests"] == 1
        assert origin_pressure["pool_acquire_attempts"] == EXPECTED_ORIGIN_ATTEMPTS_UNDER_PRESSURE
        assert origin_pressure["pool_acquire_immediate"] == 1
        assert origin_pressure["pool_acquire_waited"] == 1
        assert origin_pressure["pool_acquire_timeouts"] == 1
        assert origin_pressure["pool_acquire_wait_time_last_ns"] > 0
        assert origin_pressure["last_activity_at_ns"] > 0

        response = blocker.result(timeout=1)
        retry_response = client.get(sync_resource_http_server)
        final_stats = client.stats()

    assert response.status_code == OK
    assert retry_response.status_code == OK
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0


def test_different_origins_do_not_share_per_origin_slots(
    sync_resource_http_server: str,
    secondary_sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_active_requests_per_origin=1,
        max_pending_requests=1,
    )

    with (
        foghttp.Client(limits=limits) as client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        blocker = executor.submit(
            client.get,
            sync_resource_http_server + SLOW_RESPONSE_PATH,
        )
        wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)

        response = client.get(secondary_sync_resource_http_server)
        state = client.dump_transport_state()
        blocker_response = blocker.result(timeout=1)

        stats = client.stats()

    assert response.status_code == OK
    assert blocker_response.status_code == OK
    assert set(state["origins"]) == {
        sync_resource_http_server,
        secondary_sync_resource_http_server,
    }
    assert state["origins"][sync_resource_http_server]["active_requests"] == 1
    assert state["origins"][secondary_sync_resource_http_server]["active_requests"] == 0
    assert state["origins"][secondary_sync_resource_http_server]["pool_acquire_immediate"] == 1
    assert stats.total_requests == EXPECTED_COMPLETED_REQUESTS
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
    assert stats.pool_acquire_timeouts == 0


def test_redirect_hop_waits_for_target_origin_slot(
    sync_resource_http_server: str,
    secondary_sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_active_requests_per_origin=1,
        max_pending_requests=1,
    )
    timeouts = foghttp.Timeouts(pool=0.05, total=1.0)
    redirect_url = redirect_to_location_url(
        sync_resource_http_server,
        status_code=FOUND,
        location=secondary_sync_resource_http_server,
    )

    with (
        foghttp.Client(follow_redirects=True, limits=limits, timeouts=timeouts) as client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        blocker = executor.submit(
            client.get,
            secondary_sync_resource_http_server + SLOW_RESPONSE_PATH,
        )
        wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)

        with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
            client.get(redirect_url)

        stats = client.stats()
        assert stats.active_requests == 1
        assert stats.pending_requests == 0
        assert stats.failed_requests == 1
        assert stats.pool_acquire_timeouts == 1

        blocker_response = blocker.result(timeout=1)
        redirected_response = client.get(redirect_url)
        final_stats = client.stats()

    assert blocker_response.status_code == OK
    assert redirected_response.status_code == OK
    assert redirected_response.url == secondary_sync_resource_http_server + "/"
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0
