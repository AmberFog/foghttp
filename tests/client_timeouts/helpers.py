__all__ = (
    "assert_timeout_diagnostic",
    "assert_timeout_error_stats",
    "assert_timeout_recovery_stats",
    "wait_for_async_stats",
    "wait_for_sync_stats",
)

from collections.abc import Callable

import foghttp
from tests.support.timeout_diagnostics import assert_timeout_diagnostic
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats

from .constants import EXPECTED_FAILED_REQUESTS, EXPECTED_REQUESTS_AFTER_RECOVERY


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


def _assert_stat(name: str, actual: object, expected: object) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)


def wait_for_sync_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    wait_for_sync_transport_stats(client, condition, message="transport stats did not settle")


async def wait_for_async_stats(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    await wait_for_async_transport_stats(client, condition, message="transport stats did not settle")
