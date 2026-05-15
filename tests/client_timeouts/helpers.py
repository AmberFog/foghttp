__all__ = (
    "assert_timeout_error_stats",
    "assert_timeout_recovery_stats",
    "wait_for_async_stats",
    "wait_for_sync_stats",
)

import asyncio
from collections.abc import Callable
import time

import foghttp

from .constants import EXPECTED_FAILED_REQUESTS, EXPECTED_REQUESTS_AFTER_RECOVERY


MAX_STATS_POLLS = 100
STATS_POLL_INTERVAL = 0.01


def assert_timeout_error_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, EXPECTED_FAILED_REQUESTS)
    _assert_stat("failed_requests", stats.failed_requests, EXPECTED_FAILED_REQUESTS)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def assert_timeout_recovery_stats(stats: foghttp.TransportStats) -> None:
    _assert_stat("total_requests", stats.total_requests, EXPECTED_REQUESTS_AFTER_RECOVERY)
    _assert_stat("failed_requests", stats.failed_requests, EXPECTED_FAILED_REQUESTS)
    _assert_stat("active_requests", stats.active_requests, 0)
    _assert_stat("pending_requests", stats.pending_requests, 0)


def _assert_stat(name: str, actual: int, expected: int) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)


def wait_for_sync_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    for _attempt in range(MAX_STATS_POLLS):
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
    for _attempt in range(MAX_STATS_POLLS):
        stats = client.stats()
        if condition(stats):
            return
        await asyncio.sleep(STATS_POLL_INTERVAL)

    stats = client.stats()
    msg = f"transport stats did not settle: {stats}"
    raise AssertionError(msg)
