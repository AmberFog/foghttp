import asyncio

import pytest

import foghttp
from foghttp.messages import CONNECTION_ACQUIRE_TIMEOUT
from foghttp.status_codes.success import OK
from tests.client_timeouts.helpers import assert_timeout_diagnostic

from .constants import SLOW_RESPONSE_PATH
from .helpers import wait_for_async_stats


CONCURRENT_REQUESTS = 2


async def test_async_global_connection_limit_waits_without_pending_request_queue(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        slow = asyncio.create_task(client.get(f"{resource_http_server}{SLOW_RESPONSE_PATH}"))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_connections == 1)

            fast = asyncio.create_task(client.get(resource_http_server))
            try:
                await wait_for_async_stats(
                    client,
                    lambda stats: stats.connection_acquire_waited == 1,
                )

                assert (await slow).status_code == OK
                assert (await fast).status_code == OK
            finally:
                if not fast.done():
                    fast.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await fast
        finally:
            if not slow.done():
                slow.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await slow

        await wait_for_async_stats(client, lambda stats: stats.active_connections == 0)
        stats = client.stats()

    assert stats.total_requests == CONCURRENT_REQUESTS
    assert stats.failed_requests == 0
    assert stats.pool_acquire_waited == 0
    assert stats.pool_acquire_timeouts == 0
    assert stats.connection_acquire_attempts == CONCURRENT_REQUESTS
    assert stats.connection_acquire_immediate == 1
    assert stats.connection_acquire_waited == 1
    assert stats.connection_acquire_timeouts == 0
    assert stats.connection_acquire_wait_time_last_ns > 0
    assert stats.connection_acquire_wait_time_max_ns >= stats.connection_acquire_wait_time_last_ns
    assert stats.connection_acquire_wait_time_total_ns >= stats.connection_acquire_wait_time_last_ns


async def test_async_global_connection_limit_timeout_uses_pool_timeout_diagnostic(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        slow = asyncio.create_task(client.get(f"{resource_http_server}{SLOW_RESPONSE_PATH}"))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_connections == 1)

            with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT) as exc_info:
                await client.get(resource_http_server)

            assert (await slow).status_code == OK
        finally:
            if not slow.done():
                slow.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await slow

        assert_timeout_diagnostic(
            exc_info.value,
            phase="connection_acquire",
            origin=resource_http_server,
            timeout=timeouts.pool,
        )
        stats = client.stats()

    assert stats.total_requests == CONCURRENT_REQUESTS
    assert stats.failed_requests == 1
    assert stats.pool_acquire_timeouts == 0
    assert stats.connection_acquire_attempts == CONCURRENT_REQUESTS
    assert stats.connection_acquire_immediate == 1
    assert stats.connection_acquire_waited == 1
    assert stats.connection_acquire_timeouts == 1


async def test_async_per_host_connection_limit_reports_origin_pressure(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=2,
        max_connections_per_host=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=0.01, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        slow = asyncio.create_task(client.get(f"{resource_http_server}{SLOW_RESPONSE_PATH}"))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_connections == 1)

            with pytest.raises(foghttp.PoolTimeout, match=CONNECTION_ACQUIRE_TIMEOUT):
                await client.get(resource_http_server)

            assert (await slow).status_code == OK
        finally:
            if not slow.done():
                slow.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await slow

        state = client.dump_transport_state()

    origin = state["origins"][resource_http_server]
    assert state["connection_acquire_timeouts"] == 1
    assert origin["connection_acquire_attempts"] == CONCURRENT_REQUESTS
    assert origin["connection_acquire_immediate"] == 1
    assert origin["connection_acquire_waited"] == 1
    assert origin["connection_acquire_timeouts"] == 1


async def test_async_cancellation_while_waiting_connection_permit_releases_state(
    resource_http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_active_requests=2,
        max_connections=1,
        max_pending_requests=0,
        keepalive=False,
    )
    timeouts = foghttp.Timeouts(pool=1.0, total=2.0)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        slow = asyncio.create_task(client.get(f"{resource_http_server}{SLOW_RESPONSE_PATH}"))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_connections == 1)

            waiter = asyncio.create_task(client.get(resource_http_server))
            try:
                await wait_for_async_stats(
                    client,
                    lambda stats: stats.connection_acquire_waited == 1,
                )

                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter

                assert (await slow).status_code == OK
                response = await client.get(resource_http_server)
            finally:
                if not waiter.done():
                    waiter.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await waiter
        finally:
            if not slow.done():
                slow.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await slow

        await wait_for_async_stats(client, lambda stats: stats.active_connections == 0)
        stats = client.stats()

    assert response.status_code == OK
    assert stats.connection_acquire_timeouts == 0
