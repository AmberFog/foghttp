__all__ = ("streaming_server",)

from collections.abc import AsyncIterator

import pytest

from .server import AsyncStreamingServer, start_async_streaming_server


@pytest.fixture
async def streaming_server() -> AsyncIterator[AsyncStreamingServer]:
    async with start_async_streaming_server() as server:
        yield server
