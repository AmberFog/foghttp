__all__ = ("sync_streaming_server",)

from collections.abc import Iterator

import pytest

from tests.client_streaming.server import SyncStreamingServer, start_sync_streaming_server


@pytest.fixture
def sync_streaming_server() -> Iterator[SyncStreamingServer]:
    with start_sync_streaming_server() as server:
        yield server
