__all__ = (
    "wait_for_idle_transport",
    "wait_for_transport_pressure",
)

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats


async def wait_for_idle_transport(client: foghttp.AsyncClient) -> None:
    await wait_for_async_transport_stats(
        client,
        lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
        message="transport state did not settle",
    )


async def wait_for_transport_pressure(
    client: foghttp.AsyncClient,
    *,
    active_requests: int,
    pending_requests: int,
) -> None:
    await wait_for_async_transport_stats(
        client,
        lambda stats: stats.active_requests == active_requests and stats.pending_requests == pending_requests,
        message=(
            f"transport pressure did not settle: expected_active={active_requests}, expected_pending={pending_requests}"
        ),
    )
