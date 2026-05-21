import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import (
    ABRUPT_BEFORE_HEADERS_PATH,
    ABRUPT_DURING_BODY_PATH,
    BODY_LIMIT,
    CANCELLATION_STORM_ACTIVE_REQUESTS,
    CANCELLATION_STORM_PENDING_REQUESTS,
    CANCELLATION_STORM_REQUESTS,
    CONCURRENT_BODY_REQUESTS,
    DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH,
    EXPECTED_BODY_BUDGET_REJECTIONS,
    EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY,
    EXPECTED_REQUESTS_AFTER_POISONED_FAILURE,
    EXPECTED_REQUESTS_AFTER_POISONED_RECOVERY,
    EXPECTED_REQUESTS_AFTER_RECOVERY,
    HEALTHY_PATH,
    INCOMPLETE_BODY_PATH,
    SLOW_BODY_PATH,
    SLOW_HEADERS_PATH,
    TOTAL_TIMEOUT,
)
from .server import FaultInjectionServer
from .state_assertions import (
    assert_client_recovered,
    assert_idle_stats,
    assert_network_failure_recovered,
    assert_poisoned_connection_not_reused,
    assert_request_count,
)
from .timeout_assertions import assert_timeout_error
from .transport_waiters import wait_for_idle_transport, wait_for_transport_pressure


RECOVERY_TIMEOUTS = foghttp.Timeouts(total=1.0)


async def test_async_slow_headers_total_timeout_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(fault_injection_server.url + SLOW_HEADERS_PATH)

        stats_after_error = client.stats()
        response = await client.get(
            fault_injection_server.url + HEALTHY_PATH,
            timeout=RECOVERY_TIMEOUTS,
        )
        final_stats = client.stats()

    assert response.status_code == OK
    assert_timeout_error(
        exc_info.value,
        stats_after_error,
        phase="response_headers",
        origin=fault_injection_server.url,
        timeout=timeouts.total,
    )
    assert_client_recovered(stats_after_error, final_stats)


async def test_async_slow_body_total_timeout_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(fault_injection_server.url + SLOW_BODY_PATH)

        stats_after_error = client.stats()
        response = await client.get(
            fault_injection_server.url + HEALTHY_PATH,
            timeout=RECOVERY_TIMEOUTS,
        )
        final_stats = client.stats()

    assert response.status_code == OK
    assert_timeout_error(
        exc_info.value,
        stats_after_error,
        phase="response_body",
        origin=fault_injection_server.url,
        timeout=timeouts.total,
    )
    assert final_stats.total_requests == EXPECTED_REQUESTS_AFTER_RECOVERY
    assert final_stats.failed_requests == EXPECTED_FAILED_REQUESTS_AFTER_RECOVERY
    assert_idle_stats(final_stats)


@pytest.mark.parametrize(
    "fault_path",
    (
        ABRUPT_BEFORE_HEADERS_PATH,
        ABRUPT_DURING_BODY_PATH,
        INCOMPLETE_BODY_PATH,
    ),
)
async def test_async_network_fault_recovers_next_request(
    fault_injection_server: FaultInjectionServer,
    fault_path: str,
) -> None:
    async with foghttp.AsyncClient(timeouts=RECOVERY_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            await client.get(fault_injection_server.url + fault_path)

        stats_after_error = client.stats()
        response = await client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    assert response.status_code == OK
    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_network_failure_recovered(stats_after_error, final_stats)


async def test_async_cancellation_storm_releases_transport_state_and_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=CANCELLATION_STORM_ACTIVE_REQUESTS,
        max_pending_requests=CANCELLATION_STORM_PENDING_REQUESTS,
    )

    async with foghttp.AsyncClient(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        tasks = [
            asyncio.create_task(client.get(fault_injection_server.url + SLOW_HEADERS_PATH))
            for _ in range(CANCELLATION_STORM_REQUESTS)
        ]
        await wait_for_transport_pressure(
            client,
            active_requests=CANCELLATION_STORM_ACTIVE_REQUESTS,
            pending_requests=CANCELLATION_STORM_PENDING_REQUESTS,
        )
        await asyncio.to_thread(
            fault_injection_server.wait_for_path_hits,
            SLOW_HEADERS_PATH,
            CANCELLATION_STORM_ACTIVE_REQUESTS,
        )

        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        await wait_for_idle_transport(client)
        stats_after_cancellation = client.stats()
        response = await client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    cancelled_results = [result for result in results if isinstance(result, asyncio.CancelledError)]

    assert len(cancelled_results) == CANCELLATION_STORM_REQUESTS
    assert response.status_code == OK
    assert_idle_stats(stats_after_cancellation)
    assert_idle_stats(final_stats)
    assert_request_count(
        fault_injection_server.snapshot(),
        SLOW_HEADERS_PATH,
        CANCELLATION_STORM_ACTIVE_REQUESTS,
    )


async def test_async_partial_body_connection_is_not_reused(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(keepalive=True, max_idle_connections_per_host=1)

    async with foghttp.AsyncClient(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        first_response = await client.get(fault_injection_server.url + HEALTHY_PATH)
        with pytest.raises(foghttp.RequestError):
            await client.get(fault_injection_server.url + ABRUPT_DURING_BODY_PATH)

        stats_after_error = client.stats()
        recovery_response = await client.get(fault_injection_server.url + HEALTHY_PATH)
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


async def test_async_delayed_eof_budget_limits_concurrent_unknown_size_bodies(
    fault_injection_server: FaultInjectionServer,
) -> None:
    limits = foghttp.Limits(
        max_response_body_size=BODY_LIMIT,
        max_buffered_response_bytes=BODY_LIMIT,
    )
    url = f"{fault_injection_server.url}{DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH}/{BODY_LIMIT}"

    async with foghttp.AsyncClient(limits=limits, timeouts=RECOVERY_TIMEOUTS) as client:
        results = await asyncio.gather(
            *(client.get(url) for _ in range(CONCURRENT_BODY_REQUESTS)),
            return_exceptions=True,
        )
        stats = client.stats()

    responses = [result for result in results if isinstance(result, foghttp.Response)]
    errors = [result for result in results if isinstance(result, foghttp.ResponseBodyBudgetExceededError)]
    unexpected_results = [
        result
        for result in results
        if not isinstance(result, (foghttp.Response, foghttp.ResponseBodyBudgetExceededError))
    ]

    assert unexpected_results == []
    assert len(responses) == 1
    assert responses[0].status_code == OK
    assert responses[0].content == b"x" * BODY_LIMIT
    assert len(errors) == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.total_requests == CONCURRENT_BODY_REQUESTS
    assert stats.failed_requests == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.buffered_response_budget_rejections == EXPECTED_BODY_BUDGET_REJECTIONS
    assert_idle_stats(stats)
