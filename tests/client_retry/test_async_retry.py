import asyncio

import pytest

import foghttp
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats

from .assertions import retry_events
from .constants import (
    CLOSE_THEN_OK_PATH,
    EARLY_STATUS_THEN_OK_PATH,
    EXPECTED_ATTEMPTS,
    STATUS_THEN_OK_PATH,
)
from .server import RetryTestServer
from .sources import AsyncBodyFactory, CoordinatedReplayBodyFactory


EXPECTED_REPLAY_BODY = b"async-second-attempt-body"
STALE_REPLAY_BODY = b"stale-async-first-attempt-body"


async def test_async_retries_status_with_telemetry(retry_server: RetryTestServer) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = await client.get(retry_server.url + STATUS_THEN_OK_PATH)
        stats = client.stats()

    decisions = retry_events(sink.events)
    assert response.status_code == OK
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == EXPECTED_ATTEMPTS
    assert stats.total_requests == 1
    assert stats.pool_acquire_attempts == EXPECTED_ATTEMPTS
    assert len(decisions) == 1
    assert decisions[0].status_code == SERVICE_UNAVAILABLE


async def test_async_query_replays_factory_body(retry_server: RetryTestServer) -> None:
    content = AsyncBodyFactory((b"async-", b"replay"))
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.query(
            retry_server.url + STATUS_THEN_OK_PATH,
            content=content,
        )

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert tuple(request.body for request in requests) == (b"async-replay", b"async-replay")
    assert content.calls == EXPECTED_ATTEMPTS


async def test_async_retry_isolates_sync_upload_attempts_after_early_response(
    retry_server: RetryTestServer,
) -> None:
    content = CoordinatedReplayBodyFactory(EXPECTED_REPLAY_BODY, STALE_REPLAY_BODY)
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.query(
            retry_server.url + EARLY_STATUS_THEN_OK_PATH,
            content=content,
        )

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert content.calls == EXPECTED_ATTEMPTS
    assert await asyncio.to_thread(content.first_closed.wait, 1.0)
    assert await asyncio.to_thread(content.second_closed.wait, 1.0)


async def test_async_retries_pre_header_network_failure(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.get(retry_server.url + CLOSE_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(CLOSE_THEN_OK_PATH)
    assert response.status_code == OK
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id != requests[1].connection_id


async def test_async_stream_retries_before_exposing_response(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with (
        foghttp.AsyncClient(retry=policy) as client,
        client.stream("GET", retry_server.url + STATUS_THEN_OK_PATH) as response,
    ):
        content = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert response.status_code == OK
    assert content == b"ok"
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == EXPECTED_ATTEMPTS


async def test_async_cancellation_during_backoff_releases_request_lifecycle(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=2, jitter=0)

    async with foghttp.AsyncClient(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        task = asyncio.create_task(client.get(retry_server.url + STATUS_THEN_OK_PATH))
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.total_requests == 1 and stats.pool_acquire_attempts == 1 and stats.active_requests == 0,
            message="request did not enter retry backoff",
        )
        assert task.done() is False

        task.cancel()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task

        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    assert recovery.status_code == OK
    assert getattr(exc_info.value, "retry_trace", None) is None
    assert retry_events(sink.events) == ()
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == 1
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_stream_cancellation_during_backoff_releases_request_lifecycle(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=2, jitter=0)

    async with foghttp.AsyncClient(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:

        async def open_stream() -> None:
            async with client.stream("GET", retry_server.url + STATUS_THEN_OK_PATH):
                pass

        task = asyncio.create_task(open_stream())
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.total_requests == 1 and stats.pool_acquire_attempts == 1 and stats.active_requests == 0,
            message="stream request did not enter retry backoff",
        )
        assert task.done() is False

        task.cancel()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task

        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    assert recovery.status_code == OK
    assert getattr(exc_info.value, "retry_trace", None) is None
    assert retry_events(sink.events) == ()
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == 1
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
