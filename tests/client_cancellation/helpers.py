__all__ = (
    "wait_for_no_active_requests",
    "wait_for_pending_requests",
    "wait_for_transport_state",
)

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats


async def wait_for_no_active_requests(client: foghttp.AsyncClient) -> None:
    await wait_for_async_transport_stats(
        client,
        lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
        message="request stats did not settle",
    )


async def wait_for_pending_requests(client: foghttp.AsyncClient, expected: int) -> None:
    await wait_for_async_transport_stats(
        client,
        lambda stats: stats.pending_requests == expected,
        message=f"pending requests did not settle: expected={expected}",
    )


async def wait_for_transport_state(
    client: foghttp.AsyncClient,
    *,
    active_requests: int,
    pending_requests: int,
) -> None:
    await wait_for_async_transport_stats(
        client,
        lambda stats: stats.active_requests == active_requests and stats.pending_requests == pending_requests,
        message=(
            f"transport state did not settle: expected_active={active_requests}, expected_pending={pending_requests}"
        ),
    )
