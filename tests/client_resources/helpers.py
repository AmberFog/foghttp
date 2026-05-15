__all__ = (
    "wait_for_async_stats",
    "wait_for_sync_stats",
)

import asyncio
from collections.abc import Callable
import time

import foghttp


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


def wait_for_sync_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if condition(stats):
            return
        time.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"transport stats did not settle: {stats}"
    raise AssertionError(msg)


async def wait_for_async_stats(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    for _ in range(MAX_STATS_POLLS):
        stats = client.stats()
        if condition(stats):
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"transport stats did not settle: {stats}"
    raise AssertionError(msg)
