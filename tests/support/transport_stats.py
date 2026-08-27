__all__ = (
    "wait_for_async_transport_stats",
    "wait_for_sync_transport_stats",
)

import asyncio
from collections.abc import Callable
import time
from typing import Protocol, TypeVar


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


class _RequestStats(Protocol):
    @property
    def active_requests(self) -> int: ...

    @property
    def pending_requests(self) -> int: ...


_StatsT_co = TypeVar("_StatsT_co", bound=_RequestStats, covariant=True)


class _StatsSource(Protocol[_StatsT_co]):
    def stats(self) -> _StatsT_co: ...


def wait_for_sync_transport_stats(
    client: _StatsSource[_StatsT_co],
    condition: Callable[[_StatsT_co], bool],
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
    client: _StatsSource[_StatsT_co],
    condition: Callable[[_StatsT_co], bool],
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


def _stats_message(message: str, stats: _RequestStats) -> str:
    return f"{message}: active={stats.active_requests}, pending={stats.pending_requests}, stats={stats}"
