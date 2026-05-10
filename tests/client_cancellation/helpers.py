__all__ = ("wait_for_no_active_requests",)

import asyncio

import foghttp


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


async def wait_for_no_active_requests(client: foghttp.AsyncClient) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if stats.active_connections == 0 and stats.pending_acquires == 0:
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"request stats did not settle: active={stats.active_connections}, pending={stats.pending_acquires}"
    raise AssertionError(
        msg,
    )
