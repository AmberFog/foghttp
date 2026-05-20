__all__ = (
    "assert_timeout_diagnostic",
    "assert_timeout_error_stats",
    "assert_timeout_recovery_stats",
    "wait_for_async_stats",
    "wait_for_sync_stats",
)

import asyncio
from collections.abc import Callable
import time

import pytest

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


def assert_timeout_diagnostic(
    error: foghttp.TimeoutError,
    *,
    phase: str,
    origin: str,
    timeout: float,
    redirect_hop: int = 0,
) -> None:
    diagnostic = _assert_timeout_diagnostic_present(error.diagnostic)
    _assert_stat("phase", diagnostic.phase, phase)
    _assert_stat("origin", diagnostic.origin, origin)
    _assert_stat("timeout", diagnostic.timeout, pytest.approx(timeout))
    if diagnostic.elapsed < 0:
        msg = f"elapsed: expected non-negative value, got {diagnostic.elapsed}"
        raise AssertionError(msg)
    _assert_stat("redirect_hop", diagnostic.redirect_hop, redirect_hop)
    _assert_stat("error.phase", error.phase, diagnostic.phase)
    _assert_stat("error.origin", error.origin, diagnostic.origin)
    _assert_stat("error.timeout", error.timeout, diagnostic.timeout)
    _assert_stat("error.redirect_hop", error.redirect_hop, diagnostic.redirect_hop)


def _assert_timeout_diagnostic_present(
    diagnostic: foghttp.TimeoutDiagnostic | None,
) -> foghttp.TimeoutDiagnostic:
    if diagnostic is None:
        msg = "expected timeout diagnostic"
        raise AssertionError(msg)
    return diagnostic


def _assert_stat(name: str, actual: object, expected: object) -> None:
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
