from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import (
    EXPECTED_REQUESTS_AFTER_POOL_WAIT_RECOVERY,
    RECOVERY_TOTAL_TIMEOUT,
    SENSITIVE_QUERY,
    SLOW_RESPONSE_PATH,
    SLOW_UPLOAD_BODY_SIZE,
    SLOW_UPLOAD_PATH,
    TOTAL_TIMEOUT,
    WRITE_TIMEOUT,
    WRITE_TIMEOUT_TOTAL,
)
from .helpers import (
    assert_timeout_diagnostic,
    assert_timeout_error_stats,
    assert_timeout_recovery_stats,
    wait_for_sync_stats,
)


def test_sync_total_timeout_maps_to_generic_timeout_and_client_recovers(
    sync_timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            client.get(sync_timeout_http_server + SLOW_RESPONSE_PATH + SENSITIVE_QUERY)

        stats_after_error = client.stats()
        response = client.get(
            sync_timeout_http_server,
            timeout=foghttp.Timeouts(total=RECOVERY_TOTAL_TIMEOUT),
        )
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert SENSITIVE_QUERY not in str(exc_info.value)
    assert_timeout_diagnostic(
        exc_info.value,
        phase="response_headers",
        origin=sync_timeout_http_server,
        timeout=TOTAL_TIMEOUT,
    )
    assert_timeout_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_timeout_recovery_stats(final_stats)


def test_sync_total_timeout_wins_over_longer_pool_timeout(
    sync_timeout_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)
    default_timeouts = foghttp.Timeouts(pool=1.0, total=RECOVERY_TOTAL_TIMEOUT)
    waiting_timeouts = foghttp.Timeouts(pool=1.0, total=TOTAL_TIMEOUT)

    with (
        foghttp.Client(limits=limits, timeouts=default_timeouts) as client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        blocker = executor.submit(client.get, sync_timeout_http_server + SLOW_RESPONSE_PATH)
        wait_for_sync_stats(client, lambda stats: stats.active_requests == 1)

        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            client.get(sync_timeout_http_server, timeout=waiting_timeouts)

        stats_after_error = client.stats()
        blocker_response = blocker.result(timeout=1)
        recovery_response = client.get(sync_timeout_http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert_timeout_diagnostic(
        exc_info.value,
        phase="pool_acquire",
        origin=sync_timeout_http_server,
        timeout=TOTAL_TIMEOUT,
    )
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


def test_sync_request_body_write_timeout_maps_to_write_timeout(
    sync_timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(write=WRITE_TIMEOUT, total=WRITE_TIMEOUT_TOTAL)
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info:
            client.post(sync_timeout_http_server + SLOW_UPLOAD_PATH, content=body)

        stats_after_error = client.stats()
        response = client.get(sync_timeout_http_server)
        final_stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="request_body",
        origin=sync_timeout_http_server,
        timeout=WRITE_TIMEOUT,
    )
    assert_timeout_error_stats(stats_after_error)
    assert stats_after_error.connections_aborted == 1
    assert response.status_code == OK
    assert_timeout_recovery_stats(final_stats)
