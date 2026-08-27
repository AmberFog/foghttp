import asyncio
from collections.abc import AsyncIterator

import pytest

import foghttp
from foghttp.status_codes.client_error import PAYLOAD_TOO_LARGE
from foghttp.status_codes.success import OK
from tests.client_multipart.sources import BlockingAsyncChunks

from .constants import (
    EARLY_CLOSE_RESPONSE_PATH,
    EARLY_RESPONSE_PATH,
    EXPECTED_CONCURRENT_REQUESTS,
    EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY,
    EXPECTED_REQUESTS_AFTER_POOL_WAIT_RECOVERY,
    EXPECTED_REQUESTS_AFTER_REUSED_TIMEOUT,
    EXPECTED_REQUESTS_AFTER_REUSED_TIMEOUT_RECOVERY,
    RECOVERY_TOTAL_TIMEOUT,
    SENSITIVE_QUERY,
    SLOW_RESPONSE_PATH,
    SLOW_UPLOAD_BODY_SIZE,
    SLOW_UPLOAD_PATH,
    SLOW_UPLOAD_RESPONSE_PATH,
    TOTAL_TIMEOUT,
    WRITE_TIMEOUT,
    WRITE_TIMEOUT_TOTAL,
)
from .helpers import (
    assert_timeout_diagnostic,
    assert_timeout_error_stats,
    assert_timeout_recovery_stats,
    wait_for_async_stats,
)


@pytest.mark.parametrize("streaming", [False, True], ids=["buffered", "chunked"])
@pytest.mark.parametrize(
    "path",
    [EARLY_RESPONSE_PATH, EARLY_CLOSE_RESPONSE_PATH],
    ids=["keep-alive", "connection-close"],
)
async def test_async_early_response_does_not_reuse_incomplete_upload(
    early_response_http_server: str,
    *,
    path: str,
    streaming: bool,
) -> None:
    timeouts = foghttp.Timeouts(write=WRITE_TIMEOUT, total=WRITE_TIMEOUT_TOTAL)
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        content = _single_chunk(body) if streaming else body
        response = await client.post(
            early_response_http_server + path,
            content=content,
        )
        await wait_for_async_stats(
            client,
            lambda stats: (
                stats.connections_aborted == 1 and stats.active_connections == 0 and stats.idle_connections == 0
            ),
        )
        stats_after_response = client.stats()
        recovery_response = await client.get(early_response_http_server)
        final_stats = client.stats()

    assert response.status_code == PAYLOAD_TOO_LARGE
    assert stats_after_response.connections_opened == 1
    assert stats_after_response.connections_reused == 0
    assert stats_after_response.connections_aborted == 1
    assert stats_after_response.active_connections == 0
    assert stats_after_response.idle_connections == 0
    assert recovery_response.status_code == OK
    assert final_stats.connections_opened == EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY
    assert final_stats.connections_reused == 0


async def _single_chunk(body: bytes) -> AsyncIterator[bytes]:
    yield body


async def test_async_early_stream_response_aborts_incomplete_chunked_upload(
    early_response_http_server: str,
) -> None:
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    async with foghttp.AsyncClient() as client:
        async with client.stream(
            "POST",
            early_response_http_server + EARLY_RESPONSE_PATH,
            content=_single_chunk(body),
        ) as response:
            response_body = b"".join([chunk async for chunk in response.aiter_bytes()])
        await wait_for_async_stats(
            client,
            lambda stats: (
                stats.connections_aborted == 1 and stats.active_connections == 0 and stats.idle_connections == 0
            ),
        )
        stats_after_response = client.stats()
        recovery_response = await client.get(early_response_http_server)
        final_stats = client.stats()

    assert response.status_code == PAYLOAD_TOO_LARGE
    assert response_body == b""
    assert stats_after_response.connections_opened == 1
    assert stats_after_response.connections_reused == 0
    assert recovery_response.status_code == OK
    assert final_stats.connections_opened == EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY
    assert final_stats.connections_reused == 0


async def test_async_waiting_request_cannot_reuse_early_response_connection(
    early_response_http_server: str,
) -> None:
    body = b"x" * SLOW_UPLOAD_BODY_SIZE
    limits = foghttp.Limits(max_connections=1)

    async with (
        foghttp.AsyncClient(limits=limits) as client,
        client.stream(
            "POST",
            early_response_http_server + EARLY_RESPONSE_PATH,
            content=_single_chunk(body),
        ) as response,
        asyncio.TaskGroup() as requests,
    ):
        recovery_task = requests.create_task(client.get(early_response_http_server))
        await wait_for_async_stats(
            client,
            lambda stats: (
                stats.active_requests == EXPECTED_CONCURRENT_REQUESTS
                and stats.connections_opened == 1
                and stats.connections_reused == 0
            ),
        )
        response_body = b"".join([chunk async for chunk in response.aiter_bytes()])
        recovery_response = await recovery_task
        final_stats = client.stats()

    assert response.status_code == PAYLOAD_TOO_LARGE
    assert response_body == b""
    assert recovery_response.status_code == OK
    assert final_stats.connections_opened == EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY
    assert final_stats.connections_reused == 0
    assert final_stats.connections_aborted == 1


async def test_async_total_timeout_maps_to_generic_timeout_and_client_recovers(
    timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(timeout_http_server + SLOW_RESPONSE_PATH + SENSITIVE_QUERY)

        stats_after_error = client.stats()
        response = await client.get(
            timeout_http_server,
            timeout=foghttp.Timeouts(total=RECOVERY_TOTAL_TIMEOUT),
        )
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert SENSITIVE_QUERY not in str(exc_info.value)
    assert_timeout_diagnostic(
        exc_info.value,
        phase="response_headers",
        origin=timeout_http_server,
        timeout=TOTAL_TIMEOUT,
    )
    assert_timeout_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_timeout_recovery_stats(final_stats)


async def test_async_total_timeout_wins_over_longer_pool_timeout(
    timeout_http_server: str,
) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=1)
    default_timeouts = foghttp.Timeouts(pool=1.0, total=RECOVERY_TOTAL_TIMEOUT)
    waiting_timeouts = foghttp.Timeouts(pool=1.0, total=TOTAL_TIMEOUT)

    async with foghttp.AsyncClient(limits=limits, timeouts=default_timeouts) as client:
        blocker = asyncio.create_task(client.get(timeout_http_server + SLOW_RESPONSE_PATH))
        try:
            await wait_for_async_stats(client, lambda stats: stats.active_requests == 1)

            with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
                await client.get(timeout_http_server, timeout=waiting_timeouts)

            stats_after_error = client.stats()
            blocker_response = await blocker
            recovery_response = await client.get(timeout_http_server)
            final_stats = client.stats()
        finally:
            if not blocker.done():
                blocker.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await blocker

    assert not isinstance(exc_info.value, foghttp.PoolTimeout)
    assert_timeout_diagnostic(
        exc_info.value,
        phase="pool_acquire",
        origin=timeout_http_server,
        timeout=TOTAL_TIMEOUT,
    )
    assert stats_after_error.active_requests == 1
    assert stats_after_error.pending_requests == 0
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.pool_acquire_timeouts == 0
    assert blocker_response.status_code == OK
    assert recovery_response.status_code == OK
    assert final_stats.total_requests == EXPECTED_REQUESTS_AFTER_POOL_WAIT_RECOVERY
    assert final_stats.failed_requests == 1
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0
    assert final_stats.pool_acquire_timeouts == 0


async def test_async_cancellation_during_request_body_write_releases_request_slot(
    timeout_http_server: str,
    slow_upload_request_headers_received: asyncio.Event,
) -> None:
    timeouts = foghttp.Timeouts(write=RECOVERY_TOTAL_TIMEOUT, total=RECOVERY_TOTAL_TIMEOUT)
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        task = asyncio.create_task(client.post(timeout_http_server + SLOW_UPLOAD_PATH, content=body))
        await asyncio.wait_for(slow_upload_request_headers_received.wait(), timeout=1.0)
        await wait_for_async_stats(
            client,
            lambda stats: stats.active_requests == 1 and stats.connections_opened == 1,
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await wait_for_async_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.connections_aborted == 1,
        )
        stats_after_cancellation = client.stats()
        response = await client.get(timeout_http_server)
        final_stats = client.stats()

    assert response.status_code == OK
    assert stats_after_cancellation.connections_opened == 1
    assert stats_after_cancellation.connections_aborted == 1
    assert final_stats.connections_opened == EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY
    assert final_stats.connections_reused == 0
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0


async def test_async_request_body_write_timeout_maps_to_write_timeout(
    timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(write=WRITE_TIMEOUT, total=WRITE_TIMEOUT_TOTAL)
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        warmup_response = await client.get(timeout_http_server)

        with pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info:
            await client.post(timeout_http_server + SLOW_UPLOAD_PATH, content=body)

        await wait_for_async_stats(
            client,
            lambda stats: (
                stats.active_requests == 0
                and stats.pending_requests == 0
                and stats.connections_aborted == 1
                and stats.active_connections == 0
                and stats.idle_connections == 0
            ),
        )
        stats_after_error = client.stats()
        response = await client.get(timeout_http_server)
        final_stats = client.stats()

    assert warmup_response.status_code == OK
    assert_timeout_diagnostic(
        exc_info.value,
        phase="request_body",
        origin=timeout_http_server,
        timeout=WRITE_TIMEOUT,
    )
    assert_timeout_error_stats(
        stats_after_error,
        expected_total_requests=EXPECTED_REQUESTS_AFTER_REUSED_TIMEOUT,
    )
    assert stats_after_error.connections_opened == 1
    assert stats_after_error.connections_reused == 1
    assert stats_after_error.connections_aborted == 1
    assert stats_after_error.active_connections == 0
    assert stats_after_error.idle_connections == 0
    assert response.status_code == OK
    assert_timeout_recovery_stats(
        final_stats,
        expected_total_requests=EXPECTED_REQUESTS_AFTER_REUSED_TIMEOUT_RECOVERY,
    )
    assert final_stats.connections_opened == EXPECTED_CONNECTIONS_AFTER_ABORT_RECOVERY
    assert final_stats.connections_reused == 1


async def test_async_post_headers_write_timeout_maps_to_write_timeout(
    timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(write=WRITE_TIMEOUT, total=WRITE_TIMEOUT_TOTAL)
    body = b"x" * SLOW_UPLOAD_BODY_SIZE

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.WriteTimeout) as exc_info:
            await client.post(timeout_http_server + SLOW_UPLOAD_RESPONSE_PATH, content=body)
        stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="request_body",
        origin=timeout_http_server,
        timeout=WRITE_TIMEOUT,
    )
    assert stats.failed_requests == 1
    assert stats.connections_aborted == 1


async def test_async_post_headers_streaming_write_timeout_maps_to_write_timeout(
    timeout_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(write=WRITE_TIMEOUT, total=WRITE_TIMEOUT_TOTAL)
    content = BlockingAsyncChunks((b"first", b"second"))

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.WriteTimeout) as exc_info:
            await client.post(
                timeout_http_server + SLOW_UPLOAD_RESPONSE_PATH,
                content=content,
            )
        stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="request_body",
        origin=timeout_http_server,
        timeout=WRITE_TIMEOUT,
    )
    assert content.closed is True
    assert content.close_calls == 1
    assert stats.failed_requests == 1
    assert stats.connections_aborted == 1
