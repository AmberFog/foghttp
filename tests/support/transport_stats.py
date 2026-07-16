__all__ = (
    "wait_for_async_transport_stats",
    "wait_for_sync_transport_stats",
)

import asyncio
from collections.abc import Callable
import time

import foghttp


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


def wait_for_sync_transport_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
    *,
    message: str,
) -> None:
    stats = client.stats()
    for _attempt in range(MAX_STATS_POLLS):
        if condition(stats):
            return
        time.sleep(STATS_POLL_INTERVAL)
        stats = client.stats()

    if condition(stats):
        return
    raise AssertionError(_stats_message(message, stats))


async def wait_for_async_transport_stats(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportStats], bool],
    *,
    message: str,
) -> None:
    stats = client.stats()
    for _attempt in range(MAX_STATS_POLLS):
        if condition(stats):
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)
        stats = client.stats()

    if condition(stats):
        return
    raise AssertionError(_stats_message(message, stats))


def _stats_message(message: str, stats: foghttp.TransportStats) -> str:
    return f"{message}: active={stats.active_requests}, pending={stats.pending_requests}, stats={stats}"
