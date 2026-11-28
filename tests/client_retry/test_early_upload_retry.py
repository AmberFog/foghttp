import asyncio

import pytest

import foghttp
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK

from .constants import EARLY_CLOSE_THEN_OK_PATH, EARLY_STATUS_THEN_OK_PATH, EXPECTED_ATTEMPTS, EXPECTED_REPLAY_BODY
from .early_upload_assertions import (
    assert_early_upload_order,
    assert_non_replayable_upload_trace,
    assert_recovery_trace,
    assert_replayed_upload_trace,
)
from .server import RetryTestServer
from .sources import BlockedSyncBodySource, CoordinatedReplayBodyFactory, SyncBodyFactory


def test_sync_replayable_upload_retries_early_network_failure(
    retry_server: RetryTestServer,
    early_close_replay_body: CoordinatedReplayBodyFactory,
) -> None:
    content = early_close_replay_body
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.query(retry_server.url + EARLY_CLOSE_THEN_OK_PATH, content=content)
        assert content.first_closed.wait(timeout=1.0)
        assert content.second_closed.wait(timeout=1.0)
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_CLOSE_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert requests[0].connection_id != requests[1].connection_id
    assert content.calls == EXPECTED_ATTEMPTS
    assert_replayed_upload_trace(response, first_status_code=None, first_error_type="NetworkError")
    assert_early_upload_order(retry_server, content, early_event="early_close")
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_replayable_upload_retries_early_network_failure(
    retry_server: RetryTestServer,
    early_close_replay_body: CoordinatedReplayBodyFactory,
) -> None:
    content = early_close_replay_body
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.query(retry_server.url + EARLY_CLOSE_THEN_OK_PATH, content=content)
        assert await asyncio.to_thread(content.first_closed.wait, 1.0)
        assert await asyncio.to_thread(content.second_closed.wait, 1.0)
        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_CLOSE_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert requests[0].connection_id != requests[1].connection_id
    assert content.calls == EXPECTED_ATTEMPTS
    assert_replayed_upload_trace(response, first_status_code=None, first_error_type="NetworkError")
    assert_early_upload_order(retry_server, content, early_event="early_close")
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_one_shot_upload_does_not_retry_early_status(
    retry_server: RetryTestServer,
    blocked_upload_source: BlockedSyncBodySource,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.query(retry_server.url + EARLY_STATUS_THEN_OK_PATH, content=blocked_upload_source)
        assert blocked_upload_source.closed.wait(timeout=1.0)
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.content == b"retryable"
    assert len(requests) == 1
    assert_non_replayable_upload_trace(response, status_code=SERVICE_UNAVAILABLE)
    assert_early_upload_order(retry_server, blocked_upload_source)
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_one_shot_upload_does_not_retry_early_status(
    retry_server: RetryTestServer,
    blocked_upload_source: BlockedSyncBodySource,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.query(retry_server.url + EARLY_STATUS_THEN_OK_PATH, content=blocked_upload_source)
        assert await asyncio.to_thread(blocked_upload_source.closed.wait, 1.0)
        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.content == b"retryable"
    assert len(requests) == 1
    assert_non_replayable_upload_trace(response, status_code=SERVICE_UNAVAILABLE)
    assert_early_upload_order(retry_server, blocked_upload_source)
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_one_shot_upload_does_not_retry_early_network_failure(
    retry_server: RetryTestServer,
    early_close_upload_source: BlockedSyncBodySource,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            client.query(retry_server.url + EARLY_CLOSE_THEN_OK_PATH, content=early_close_upload_source)
        assert early_close_upload_source.closed.wait(timeout=1.0)
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    assert len(retry_server.snapshot().requests_for(EARLY_CLOSE_THEN_OK_PATH)) == 1
    assert_non_replayable_upload_trace(exc_info.value, status_code=None, error_type="NetworkError")
    assert_early_upload_order(retry_server, early_close_upload_source, early_event="early_close")
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_one_shot_upload_does_not_retry_early_network_failure(
    retry_server: RetryTestServer,
    early_close_upload_source: BlockedSyncBodySource,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            await client.query(retry_server.url + EARLY_CLOSE_THEN_OK_PATH, content=early_close_upload_source)
        assert await asyncio.to_thread(early_close_upload_source.closed.wait, 1.0)
        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    assert len(retry_server.snapshot().requests_for(EARLY_CLOSE_THEN_OK_PATH)) == 1
    assert_non_replayable_upload_trace(exc_info.value, status_code=None, error_type="NetworkError")
    assert_early_upload_order(retry_server, early_close_upload_source, early_event="early_close")
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_finite_upload_retries_immediate_early_status(
    retry_server: RetryTestServer,
    immediate_upload_body: SyncBodyFactory,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.query(retry_server.url + EARLY_STATUS_THEN_OK_PATH, content=immediate_upload_body)
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert immediate_upload_body.calls == EXPECTED_ATTEMPTS
    assert retry_server.snapshot().early_upload_gate_passed is None
    assert_replayed_upload_trace(response)
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_finite_upload_retries_immediate_early_status(
    retry_server: RetryTestServer,
    immediate_upload_body: SyncBodyFactory,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.query(retry_server.url + EARLY_STATUS_THEN_OK_PATH, content=immediate_upload_body)
        recovery = await client.get(retry_server.url + "/recovery")
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert immediate_upload_body.calls == EXPECTED_ATTEMPTS
    assert retry_server.snapshot().early_upload_gate_passed is None
    assert_replayed_upload_trace(response)
    assert recovery.status_code == OK
    assert_recovery_trace(recovery)
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
