__all__ = (
    "wait_for_no_active_requests",
    "wait_for_pending_requests",
    "wait_for_transport_state",
)

import asyncio

import foghttp


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


async def wait_for_no_active_requests(client: foghttp.AsyncClient) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if stats.active_requests == 0 and stats.pending_requests == 0:
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"request stats did not settle: active={stats.active_requests}, pending={stats.pending_requests}"
    raise AssertionError(
        msg,
    )


async def wait_for_pending_requests(client: foghttp.AsyncClient, expected: int) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if stats.pending_requests == expected:
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"pending requests did not settle: expected={expected}, actual={stats.pending_requests}"
    raise AssertionError(
        msg,
    )


async def wait_for_transport_state(
    client: foghttp.AsyncClient,
    *,
    active_requests: int,
    pending_requests: int,
) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if stats.active_requests == active_requests and stats.pending_requests == pending_requests:
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = (
        "transport state did not settle: "
        f"active={stats.active_requests}, pending={stats.pending_requests}, "
        f"expected_active={active_requests}, expected_pending={pending_requests}"
    )
    raise AssertionError(
        msg,
    )
