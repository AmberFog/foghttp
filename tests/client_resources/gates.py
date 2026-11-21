__all__ = ("AsyncResponseGate", "SyncResponseGate")

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
import threading


_REQUEST_START_TIMEOUT = 2.0


class SyncResponseGate:
    """Hold a response on one test server until the contention scenario exits."""

    def __init__(self) -> None:
        self.request_started = threading.Event()
        self.release_response = threading.Event()

    @contextmanager
    def hold(self) -> Iterator[None]:
        try:
            if not self.request_started.wait(timeout=_REQUEST_START_TIMEOUT):
                msg = "resource server did not receive the blocking request"
                raise AssertionError(msg)
            yield
        finally:
            self.release_response.set()


class AsyncResponseGate:
    """Hold a response on the server loop until the contention scenario exits."""

    def __init__(self) -> None:
        self.request_started = asyncio.Event()
        self.release_response = asyncio.Event()

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(_REQUEST_START_TIMEOUT):
                await self.request_started.wait()
            yield
        finally:
            self.release_response.set()
