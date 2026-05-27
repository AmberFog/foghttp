import asyncio

import foghttp
from foghttp.status_codes.success import OK

from .constants import DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH, HEALTHY_PATH
from .server import FaultInjectionServer
from .state_assertions import assert_faulted_connection_not_reused, assert_idle_stats
from .transport_waiters import wait_for_idle_transport, wait_for_transport_pressure


RECOVERY_TIMEOUTS = foghttp.Timeouts(total=1.0)


async def test_async_peer_close_during_cancellation_releases_transport_state_and_recovers(
    fault_injection_server: FaultInjectionServer,
) -> None:
    async with foghttp.AsyncClient(timeouts=RECOVERY_TIMEOUTS) as client:
        task = asyncio.create_task(
            client.get(fault_injection_server.url + DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH),
        )
        await asyncio.to_thread(
            fault_injection_server.wait_for_path_hits,
            DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH,
            1,
        )
        await wait_for_transport_pressure(client, active_requests=1, pending_requests=0)

        try:
            task.cancel()
            fault_injection_server.release_delayed_peer_close()
            request_result = (await asyncio.gather(task, return_exceptions=True))[0]
        finally:
            fault_injection_server.release_delayed_peer_close()

        await wait_for_idle_transport(client)
        stats_after_race = client.stats()
        response = await client.get(fault_injection_server.url + HEALTHY_PATH)
        final_stats = client.stats()

    assert isinstance(request_result, (asyncio.CancelledError, foghttp.RequestError))
    assert not isinstance(request_result, foghttp.TimeoutError)
    assert response.status_code == OK
    assert_idle_stats(stats_after_race)
    assert_idle_stats(final_stats)
    assert_faulted_connection_not_reused(
        response.json(),
        fault_injection_server.snapshot(),
        DELAYED_PEER_CLOSE_BEFORE_HEADERS_PATH,
    )
