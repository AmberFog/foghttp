__all__ = (
    "codec_streaming_server",
    "streaming_server",
    "sync_codec_streaming_server",
    "sync_streaming_server",
)

from collections.abc import AsyncIterator, Iterator

import pytest

from .constants import BOM_TEXT_STREAM_CHUNKS
from .server import (
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


@pytest.fixture
async def codec_streaming_server(content_type: str) -> AsyncIterator[AsyncStreamingServer]:
    async with start_async_streaming_server(content_type=content_type, chunks=BOM_TEXT_STREAM_CHUNKS) as server:
        yield server


@pytest.fixture
def sync_codec_streaming_server(content_type: str) -> Iterator[SyncStreamingServer]:
    with start_sync_streaming_server(content_type=content_type, chunks=BOM_TEXT_STREAM_CHUNKS) as server:
        yield server
