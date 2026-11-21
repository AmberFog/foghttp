from collections.abc import Iterator

import pytest

from .constants import (
    ASYNC_EXPECTED_REPLAY_BODY,
    ASYNC_STALE_REPLAY_BODY,
    EARLY_CLOSE_THEN_OK_PATH,
    EXPECTED_REPLAY_BODY,
    STALE_REPLAY_BODY,
)
from .server import RetryTestServer, start_retry_test_server
from .sources import BlockedSyncBodySource, CoordinatedReplayBodyFactory, SyncBodyFactory


@pytest.fixture
def retry_server() -> Iterator[RetryTestServer]:
    with start_retry_test_server() as server:
        yield server


@pytest.fixture
def sync_early_replay_body(retry_server: RetryTestServer) -> CoordinatedReplayBodyFactory:
    content = CoordinatedReplayBodyFactory(
        EXPECTED_REPLAY_BODY,
        STALE_REPLAY_BODY,
        first_start=retry_server.first_upload_gate_waiting,
    )
    retry_server.coordinate_upload(content.first_waiting)
    return content


@pytest.fixture
def async_early_replay_body(retry_server: RetryTestServer) -> CoordinatedReplayBodyFactory:
    content = CoordinatedReplayBodyFactory(
        ASYNC_EXPECTED_REPLAY_BODY,
        ASYNC_STALE_REPLAY_BODY,
        first_start=retry_server.first_upload_gate_waiting,
    )
    retry_server.coordinate_upload(content.first_waiting)
    return content


@pytest.fixture
def early_close_replay_body(
    retry_server: RetryTestServer,
    sync_early_replay_body: CoordinatedReplayBodyFactory,
) -> CoordinatedReplayBodyFactory:
    retry_server.coordinate_upload(sync_early_replay_body.first_waiting, path=EARLY_CLOSE_THEN_OK_PATH)
    return sync_early_replay_body


@pytest.fixture
def blocked_upload_source(retry_server: RetryTestServer) -> Iterator[BlockedSyncBodySource]:
    content = BlockedSyncBodySource(
        b"one-shot-prefix",
        first_start=retry_server.first_upload_gate_waiting,
    )
    retry_server.coordinate_upload(content.first_waiting)
    try:
        yield content
    finally:
        content.close()


@pytest.fixture
def early_close_upload_source(
    retry_server: RetryTestServer,
    blocked_upload_source: BlockedSyncBodySource,
) -> BlockedSyncBodySource:
    retry_server.coordinate_upload(blocked_upload_source.first_waiting, path=EARLY_CLOSE_THEN_OK_PATH)
    return blocked_upload_source


@pytest.fixture
def immediate_upload_body() -> SyncBodyFactory:
    return SyncBodyFactory((EXPECTED_REPLAY_BODY,))
