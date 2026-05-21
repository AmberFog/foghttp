from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.success import OK

from .constants import (
    ABRUPT_BEFORE_HEADERS_PATH,
    ABRUPT_DURING_BODY_PATH,
    BODY_LIMIT,
    BODY_TOO_LARGE_SIZE,
    CONCURRENT_BODY_REQUESTS,
    DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH,
    EXPECTED_BODY_BUDGET_REJECTIONS,
    EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY,
    EXPECTED_REQUESTS_AFTER_POISONED_FAILURE,
    EXPECTED_REQUESTS_AFTER_POISONED_RECOVERY,
    HEALTHY_PATH,
    INCOMPLETE_BODY_PATH,
    INVALID_SIZE_SEGMENT,
    NEGATIVE_SIZE_SEGMENT,
    SLOW_BODY_PATH,
    SLOW_HEADERS_PATH,
    TOTAL_TIMEOUT,
)
from .server import FaultInjectionServer
from .state_assertions import (
    assert_client_recovered,
    assert_healthy_connection_reused,
    assert_idle_stats,
    assert_network_failure_recovered,
    assert_poisoned_connection_not_reused,
)
from .timeout_assertions import assert_timeout_error


RECOVERY_TIMEOUTS = foghttp.Timeouts(total=1.0)


def test_sync_healthy_fault_server_route_reuses_keepalive_connection(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)

    with foghttp.Client(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        first_response = client.get(fault_injection_server.url + HEALTHY_PATH)
        second_response = client.get(fault_injection_server.url + HEALTHY_PATH)
        stats = client.stats()

    assert first_response.status_code == OK
    assert second_response.status_code == OK
    assert_idle_stats(stats)
    assert_healthy_connection_reused(
        first_response.json(),
        second_response.json(),
        fault_injection_server.snapshot(),
    )


def test_sync_slow_headers_total_timeout_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            client.get(fault_injection_server.url + SLOW_HEADERS_PATH)

        stats_after_error = client.stats()
        response = client.get(
            fault_injection_server.url + HEALTHY_PATH,
            timeout=RECOVERY_TIMEOUTS,
        )
        final_stats = client.stats()

    assert response.status_code == OK
    assert response.content != b""
    assert_timeout_error(
        exc_info.value,
        stats_after_error,
        phase="response_headers",
        origin=fault_injection_server.url,
        timeout=timeouts.total,
    )
    assert_client_recovered(stats_after_error, final_stats)


def test_sync_slow_body_total_timeout_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            client.get(fault_injection_server.url + SLOW_BODY_PATH)

        stats_after_error = client.stats()
        response = client.get(
            fault_injection_server.url + HEALTHY_PATH,
            timeout=RECOVERY_TIMEOUTS,
        )
        final_stats = client.stats()

    assert response.status_code == OK
    assert response.content != b""
    assert_timeout_error(
        exc_info.value,
        stats_after_error,
        phase="response_body",
        origin=fault_injection_server.url,
        timeout=timeouts.total,
    )
    assert_client_recovered(stats_after_error, final_stats)


@pytest.mark.parametrize(
    "fault_path",
    (
        pytest.param(ABRUPT_BEFORE_HEADERS_PATH, id="abrupt-before-headers"),
        pytest.param(ABRUPT_DURING_BODY_PATH, id="abrupt-during-body"),
        pytest.param(INCOMPLETE_BODY_PATH, id="incomplete-body"),
    ),
)
def test_sync_network_fault_recovers_next_request(
    fault_injection_server: FaultInjectionServer,
    fault_path: str,
) -> None:
    with foghttp.Client(timeouts=RECOVERY_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(fault_injection_server.url + fault_path)

        stats_after_error = client.stats()
        response = client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    assert response.status_code == OK
    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_network_failure_recovered(stats_after_error, final_stats)


def test_sync_partial_body_connection_is_not_reused(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)

    with foghttp.Client(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        first_response = client.get(fault_injection_server.url + HEALTHY_PATH)
        with pytest.raises(foghttp.RequestError):
            client.get(fault_injection_server.url + ABRUPT_DURING_BODY_PATH)

        stats_after_error = client.stats()
        recovery_response = client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    assert first_response.status_code == OK
    assert recovery_response.status_code == OK
    assert stats_after_error.total_requests == EXPECTED_REQUESTS_AFTER_POISONED_FAILURE
    assert stats_after_error.failed_requests == EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY
    assert final_stats.total_requests == EXPECTED_REQUESTS_AFTER_POISONED_RECOVERY
    assert final_stats.failed_requests == EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY
    assert_idle_stats(final_stats)
    assert_poisoned_connection_not_reused(
        first_response.json(),
        recovery_response.json(),
        fault_injection_server.snapshot(),
    )


def test_sync_delayed_eof_body_limit_failure_releases_resources(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(max_response_body_size=BODY_LIMIT)

    with foghttp.Client(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            client.get(f"{fault_injection_server.url}{DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH}/{BODY_TOO_LARGE_SIZE}")

        stats_after_error = client.stats()
        response = client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    assert response.status_code == OK
    assert_client_recovered(stats_after_error, final_stats)


@pytest.mark.parametrize(
    "size_segment",
    (
        pytest.param(INVALID_SIZE_SEGMENT, id="not-an-int-size"),
        pytest.param(NEGATIVE_SIZE_SEGMENT, id="negative-size"),
    ),
)
def test_sync_invalid_delayed_eof_size_returns_not_found(
    fault_injection_server: FaultInjectionServer,
    size_segment: str,
) -> None:
    with foghttp.Client(timeouts=RECOVERY_TIMEOUTS) as client:
        response = client.get(
            f"{fault_injection_server.url}{DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH}/{size_segment}",
        )
        stats = client.stats()

    assert response.status_code == NOT_FOUND
    assert response.content == b""
    assert_idle_stats(stats)


def test_sync_delayed_eof_budget_limits_concurrent_unknown_size_bodies(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(
        max_response_body_size=BODY_LIMIT,
        max_buffered_response_bytes=BODY_LIMIT,
    )
    url = f"{fault_injection_server.url}{DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH}/{BODY_LIMIT}"

    with foghttp.Client(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        with ThreadPoolExecutor(max_workers=CONCURRENT_BODY_REQUESTS) as executor:
            futures = [executor.submit(client.get, url) for _ in range(CONCURRENT_BODY_REQUESTS)]
            results: list[foghttp.Response | BaseException] = []
            for future in futures:
                try:
                    results.append(future.result())
                except foghttp.ResponseBodyBudgetExceededError as error:
                    results.append(error)

        stats = client.stats()

    responses = [result for result in results if isinstance(result, foghttp.Response)]
    errors = [result for result in results if isinstance(result, foghttp.ResponseBodyBudgetExceededError)]

    assert len(responses) == 1
    assert responses[0].status_code == OK
    assert responses[0].content == b"x" * BODY_LIMIT
    assert len(errors) == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.total_requests == CONCURRENT_BODY_REQUESTS
    assert stats.failed_requests == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.buffered_response_budget_rejections == EXPECTED_BODY_BUDGET_REJECTIONS
    assert_idle_stats(stats)
