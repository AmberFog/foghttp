from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)

import pytest

import foghttp
from tests.support.transport_stats import wait_for_sync_transport_stats

from .constants import DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH
from .server import FaultInjectionServer
from .state_assertions import assert_request_count


RECOVERY_TIMEOUTS = foghttp.Timeouts(total=1.0)
CLOSE_BLOCKED_TIMEOUT = 0.05
REQUEST_RESULT_TIMEOUT = 1.0


def test_sync_close_waits_for_peer_close_in_flight_request(
    fault_injection_server: FaultInjectionServer,
) -> None:
    with (
        foghttp.Client(timeouts=RECOVERY_TIMEOUTS) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        request_future = executor.submit(
            client.get,
            fault_injection_server.url + DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH,
        )
        fault_injection_server.wait_for_path_hits(DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH, 1)
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 1,
            message="in-flight peer close request did not become active",
        )

        close_future = executor.submit(client.close)

        try:
            with pytest.raises(FutureTimeoutError):
                close_future.result(timeout=CLOSE_BLOCKED_TIMEOUT)
        finally:
            fault_injection_server.release_delayed_peer_close()

        with pytest.raises(foghttp.RequestError) as exc_info:
            request_future.result(timeout=REQUEST_RESULT_TIMEOUT)
        close_future.result(timeout=REQUEST_RESULT_TIMEOUT)

    assert not isinstance(exc_info.value, foghttp.ClientClosedError)
    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_request_count(
        fault_injection_server.snapshot(),
        DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH,
        1,
    )
