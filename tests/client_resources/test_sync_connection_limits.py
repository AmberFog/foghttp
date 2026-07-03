from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest

import foghttp
from foghttp.messages import CONNECTION_ACQUIRE_TIMEOUT
from foghttp.status_codes.success import OK
from tests.client_keepalive.constants import KEEPALIVE_PATH
from tests.client_keepalive.server import start_keepalive_server
from tests.client_timeouts.helpers import assert_timeout_diagnostic

from .constants import SLOW_RESPONSE_PATH
from .helpers import wait_for_sync_stats


CONCURRENT_REQUESTS = 2
EXPECTED_IDLE_ORIGINS = 2


def test_global_connection_limit_waits_without_pending_request_queue(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow = executor.submit(client.get, f"{sync_resource_http_server}{SLOW_RESPONSE_PATH}")
            wait_for_sync_stats(client, lambda stats: stats.active_connections == 1)

            fast = executor.submit(client.get, sync_resource_http_server)
            wait_for_sync_stats(client, lambda stats: stats.connection_acquire_waited == 1)

            assert slow.result(timeout=2.0).status_code == OK
            assert fast.result(timeout=2.0).status_code == OK

        wait_for_sync_stats(client, lambda stats: stats.active_connections == 0)
        stats = client.stats()

    assert stats.total_requests == CONCURRENT_REQUESTS
    assert stats.failed_requests == 0
    assert stats.pool_acquire_waited == 0
    assert stats.pool_acquire_timeouts == 0
    assert stats.connection_acquire_attempts == CONCURRENT_REQUESTS
    assert stats.connection_acquire_immediate == 1
    assert stats.connection_acquire_waited == 1
    assert stats.connection_acquire_timeouts == 0
    assert stats.connection_acquire_wait_time_last_ns > 0
    assert stats.connection_acquire_wait_time_max_ns >= stats.connection_acquire_wait_time_last_ns
    assert stats.connection_acquire_wait_time_total_ns >= stats.connection_acquire_wait_time_last_ns


def test_global_connection_limit_timeout_uses_pool_timeout_diagnostic(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=2.0)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow = executor.submit(client.get, f"{sync_resource_http_server}{SLOW_RESPONSE_PATH}")
            wait_for_sync_stats(client, lambda stats: stats.active_connections == 1)

            fast = executor.submit(client.get, sync_resource_http_server)
            with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT) as exc_info:
                fast.result(timeout=1.0)

            assert slow.result(timeout=2.0).status_code == OK

        assert_timeout_diagnostic(
            exc_info.value,
            phase="connection_acquire",
            origin=sync_resource_http_server,
            timeout=timeouts.pool,
        )
        stats = client.stats()

    assert stats.total_requests == CONCURRENT_REQUESTS
    assert stats.failed_requests == 1
    assert stats.pool_acquire_timeouts == 0
    assert stats.connection_acquire_attempts == CONCURRENT_REQUESTS
    assert stats.connection_acquire_immediate == 1
    assert stats.connection_acquire_waited == 1
    assert stats.connection_acquire_timeouts == 1


def test_per_host_connection_limit_reports_origin_pressure(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=2,
        max_connections_per_host=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=2.0)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow = executor.submit(client.get, f"{sync_resource_http_server}{SLOW_RESPONSE_PATH}")
            wait_for_sync_stats(client, lambda stats: stats.active_connections == 1)

            fast = executor.submit(client.get, sync_resource_http_server)
            with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT):
                fast.result(timeout=1.0)

            assert slow.result(timeout=2.0).status_code == OK

        state = client.dump_transport_state()

    origin = state["origins"][sync_resource_http_server]
    assert state["connection_acquire_timeouts"] == 1
    assert origin["connection_acquire_attempts"] == CONCURRENT_REQUESTS
    assert origin["connection_acquire_immediate"] == 1
    assert origin["connection_acquire_waited"] == 1
    assert origin["connection_acquire_timeouts"] == 1


def test_default_unbounded_connection_limit_does_not_starve_new_idle_origin() -> None:
    limits = foghttp.Limits(max_idle_connections_per_host=1)

    with ExitStack() as stack:
        first_server = stack.enter_context(start_keepalive_server())
        second_server = stack.enter_context(start_keepalive_server())
        third_server = stack.enter_context(start_keepalive_server())

        with foghttp.Client(limits=limits) as client:
            assert client.get(first_server.url + KEEPALIVE_PATH).status_code == OK
            assert client.get(second_server.url + KEEPALIVE_PATH).status_code == OK
            wait_for_sync_stats(
                client,
                lambda stats: stats.idle_connections == EXPECTED_IDLE_ORIGINS,
            )

            response = client.get(third_server.url + KEEPALIVE_PATH)

    assert response.status_code == OK


def test_explicit_connection_limit_counts_idle_keepalive_connections() -> None:
    limits = foghttp.Limits(
        max_connections=1,
        max_idle_connections_per_host=1,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=1.0)

    with ExitStack() as stack:
        first_server = stack.enter_context(start_keepalive_server())
        second_server = stack.enter_context(start_keepalive_server())
        second_url = second_server.url

        with foghttp.Client(limits=limits, timeouts=timeouts) as client:
            assert client.get(first_server.url + KEEPALIVE_PATH).status_code == OK
            wait_for_sync_stats(client, lambda stats: stats.idle_connections == 1)

            with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT) as exc_info:
                client.get(second_url + KEEPALIVE_PATH)

            stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="connection_acquire",
        origin=second_url,
        timeout=timeouts.pool,
    )
    assert stats.connection_acquire_timeouts == 1


def test_closed_connection_releases_connection_permit() -> None:
    limits = foghttp.Limits(
        max_connections=1,
        max_idle_connections_per_host=0,
    )
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    with ExitStack() as stack:
        first_server = stack.enter_context(start_keepalive_server())
        second_server = stack.enter_context(start_keepalive_server())
        second_url = second_server.url

        with foghttp.Client(limits=limits, timeouts=timeouts) as client:
            assert client.get(first_server.url + KEEPALIVE_PATH).status_code == OK
            wait_for_sync_stats(client, lambda stats: stats.active_connections == 0)

            response = client.get(second_url + KEEPALIVE_PATH)

    assert response.status_code == OK


def test_zero_connection_limit_is_explicit_backpressure(
    sync_resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=1,
        max_connections=0,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=1.0)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT) as exc_info:
            client.get(sync_resource_http_server)
        stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="connection_acquire",
        origin=sync_resource_http_server,
        timeout=timeouts.pool,
    )
    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0
    assert stats.connection_acquire_attempts == 1
    assert stats.connection_acquire_waited == 1
    assert stats.connection_acquire_timeouts == 1
