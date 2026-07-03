from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp._telemetry import TELEMETRY_SNAPSHOT_SCHEMA_VERSION
from foghttp.status_codes.success import OK
from tests.client_timeouts.helpers import assert_timeout_diagnostic

from .constants import (
    GLOBAL_ACTIVE_REQUESTS_BLOCK,
    NO_POOL_BLOCK,
    SLOW_RESPONSE_PATH,
)
from .helpers import has_pending_pool_waiter, wait_for_sync_pool_diagnostics, wait_for_sync_stats


def test_dump_pool_diagnostics_reports_empty_state_before_transport_creation() -> None:
    limits = foghttp.Limits(max_active_requests=7, max_pending_requests=0)

    with foghttp.Client(limits=limits) as client:
        diagnostics = client.dump_pool_diagnostics()

    assert diagnostics == {
        "active_requests": 0,
        "pending_requests": 0,
        "pool_acquire_timeouts": 0,
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": None,
        "max_pending_requests": limits.max_pending_requests,
        "pending_queue_full": True,
        "oldest_pending_request_wait_ns": 0,
        "blocked_by": NO_POOL_BLOCK,
        "schema_version": TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_sequence": 0,
        "origins": {},
    }


def test_dump_pool_diagnostics_reports_global_active_request_pressure(
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

        diagnostics = wait_for_sync_pool_diagnostics(
            client,
            lambda diagnostics: has_pending_pool_waiter(
                diagnostics,
                origin=sync_resource_http_server,
                blocked_by=GLOBAL_ACTIVE_REQUESTS_BLOCK,
            ),
        )
        origin_diagnostics = diagnostics["origins"][sync_resource_http_server]

        blocker_response = blocker.result(timeout=1)
        waiter_response = waiter.result(timeout=1)
        final_diagnostics = client.dump_pool_diagnostics()

    assert blocker_response.status_code == OK
    assert waiter_response.status_code == OK
    assert diagnostics["active_requests"] == 1
    assert diagnostics["pending_requests"] == 1
    assert diagnostics["max_active_requests"] == limits.max_active_requests
    assert diagnostics["max_active_requests_per_origin"] is None
    assert diagnostics["max_pending_requests"] == limits.max_pending_requests
    assert diagnostics["pending_queue_full"] is True
    assert diagnostics["blocked_by"] == GLOBAL_ACTIVE_REQUESTS_BLOCK
    assert diagnostics["oldest_pending_request_wait_ns"] > 0
    assert origin_diagnostics["active_requests"] == 1
    assert origin_diagnostics["pending_requests"] == 1
    assert origin_diagnostics["blocked_by"] == GLOBAL_ACTIVE_REQUESTS_BLOCK
    assert origin_diagnostics["oldest_pending_request_wait_ns"] > 0
    assert origin_diagnostics["pool_acquire_timeouts"] == 0
    assert final_diagnostics["pending_requests"] == 0
    assert final_diagnostics["oldest_pending_request_wait_ns"] == 0
    assert final_diagnostics["blocked_by"] == NO_POOL_BLOCK
    final_origin_diagnostics = final_diagnostics["origins"][sync_resource_http_server]
    assert final_origin_diagnostics["pending_requests"] == 0
    assert final_origin_diagnostics["oldest_pending_request_wait_ns"] == 0


def test_dump_pool_diagnostics_reports_queue_full_timeout_counter(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)

    with foghttp.Client(limits=limits) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full") as exc_info:
            client.get(sync_resource_http_server)

        diagnostics = client.dump_pool_diagnostics()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="pool_acquire",
        origin=sync_resource_http_server,
        timeout=foghttp.Timeouts().pool,
    )
    assert diagnostics["pool_acquire_timeouts"] == 1
    assert diagnostics["pending_queue_full"] is True
    assert diagnostics["blocked_by"] == NO_POOL_BLOCK
    origin_diagnostics = diagnostics["origins"][sync_resource_http_server]
    assert origin_diagnostics["pool_acquire_timeouts"] == 1
    assert origin_diagnostics["pending_requests"] == 0
    assert origin_diagnostics["blocked_by"] == NO_POOL_BLOCK
