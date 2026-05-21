__all__ = (
    "has_pending_pool_waiter",
    "wait_for_async_pool_diagnostics",
    "wait_for_async_stats",
    "wait_for_sync_pool_diagnostics",
    "wait_for_sync_stats",
)

import asyncio
from collections.abc import Callable
import time

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats


MAX_DIAGNOSTICS_POLLS = 100
DIAGNOSTICS_POLL_INTERVAL = 0.01


def has_pending_pool_waiter(
    diagnostics: foghttp.PoolDiagnostics,
    *,
    origin: str,
    blocked_by: foghttp.PoolBlockingReason,
) -> bool:
    origin_diagnostics = diagnostics["origins"].get(origin)
    return (
        diagnostics["pending_requests"] == 1
        and diagnostics["blocked_by"] == blocked_by
        and diagnostics["oldest_pending_request_wait_ns"] > 0
        and origin_diagnostics is not None
        and origin_diagnostics["oldest_pending_request_wait_ns"] > 0
    )


def wait_for_sync_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    wait_for_sync_transport_stats(client, condition, message="transport stats did not settle")


def wait_for_sync_pool_diagnostics(
    client: foghttp.Client,
    condition: Callable[[foghttp.PoolDiagnostics], bool],
) -> foghttp.PoolDiagnostics:
    for _attempt in range(MAX_DIAGNOSTICS_POLLS):
        diagnostics = client.dump_pool_diagnostics()
        if condition(diagnostics):
            return diagnostics
        time.sleep(DIAGNOSTICS_POLL_INTERVAL)

    raise AssertionError(_pool_diagnostics_message(client.dump_pool_diagnostics()))


async def wait_for_async_stats(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    await wait_for_async_transport_stats(client, condition, message="transport stats did not settle")


async def wait_for_async_pool_diagnostics(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.PoolDiagnostics], bool],
) -> foghttp.PoolDiagnostics:
    for _attempt in range(MAX_DIAGNOSTICS_POLLS):
        diagnostics = client.dump_pool_diagnostics()
        if condition(diagnostics):
            return diagnostics
        await asyncio.sleep(DIAGNOSTICS_POLL_INTERVAL)

    raise AssertionError(_pool_diagnostics_message(client.dump_pool_diagnostics()))


def _pool_diagnostics_message(diagnostics: foghttp.PoolDiagnostics) -> str:
    return (
        "pool diagnostics did not settle: "
        f"active={diagnostics['active_requests']}, "
        f"pending={diagnostics['pending_requests']}, "
        f"blocked_by={diagnostics['blocked_by']}, "
        f"diagnostics={diagnostics}"
    )
