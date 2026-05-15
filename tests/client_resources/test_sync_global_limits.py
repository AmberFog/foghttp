from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .helpers import wait_for_sync_stats


def test_pending_request_queue_full(sync_resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)

    with foghttp.Client(limits=limits) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full"):
            client.get(sync_resource_http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


def test_zero_pending_queue_allows_available_request_slot(sync_resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=0)

    with foghttp.Client(limits=limits) as client:
        response = client.get(sync_resource_http_server)

        assert response.status_code == OK
        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 0
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 0


def test_pool_acquire_timeout(sync_resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
            client.get(sync_resource_http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


def test_pending_requests_are_tracked_while_waiting(sync_resource_http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.2)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.get, sync_resource_http_server)
            wait_for_sync_stats(
                client,
                lambda stats: stats.pending_requests == 1 and stats.active_requests == 0,
            )

            stats = client.stats()
            assert stats.pending_requests == 1
            assert stats.active_requests == 0
            with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
                future.result(timeout=1.0)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1
