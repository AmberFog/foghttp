__all__ = ("streaming_server", "sync_streaming_server")

from collections.abc import AsyncIterator, Iterator

import pytest

from tests.client_streaming.server import (
    AsyncStreamingServer,
    SyncStreamingServer,
    start_async_streaming_server,
    start_sync_streaming_server,
)


@pytest.fixture
async def streaming_server() -> AsyncIterator[AsyncStreamingServer]:
    async with start_async_streaming_server() as server:
        yield server


@pytest.fixture
def sync_streaming_server() -> Iterator[SyncStreamingServer]:
    with start_sync_streaming_server() as server:
        yield server
