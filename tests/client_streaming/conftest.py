__all__ = (
    "codec_streaming_server",
    "conversion_history_server",
    "streaming_history_server",
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
from .streaming_history_sources import HISTORY_BODY_SIZE, StreamingHistoryServer, start_streaming_history_server


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


@pytest.fixture(
    params=[
        pytest.param((), id="no-redirect"),
        pytest.param((b"",), id="single-empty"),
        pytest.param((b"first" * HISTORY_BODY_SIZE,), id="single-body"),
        pytest.param((b"first" * HISTORY_BODY_SIZE, b"", b"last" * HISTORY_BODY_SIZE), id="multiple-mixed-bodies"),
    ],
)
def streaming_history_server(request: pytest.FixtureRequest) -> Iterator[StreamingHistoryServer]:
    with start_streaming_history_server(request.param) as server:
        yield server


@pytest.fixture
def conversion_history_server() -> Iterator[StreamingHistoryServer]:
    bodies = (b"first" * HISTORY_BODY_SIZE, b"middle" * HISTORY_BODY_SIZE, b"last" * HISTORY_BODY_SIZE)
    with start_streaming_history_server(bodies) as server:
        yield server
