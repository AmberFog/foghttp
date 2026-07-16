__all__ = (
    "AsyncBodyFactory",
    "CoordinatedReplayBodyFactory",
    "FailOnReplayBodyFactory",
    "FailingSyncBodyFactory",
    "SyncBodyFactory",
    "async_chunks",
    "sync_chunks",
)

import asyncio
from collections.abc import AsyncIterator, Iterator
import threading


SOURCE_COORDINATION_TIMEOUT = 2.0
SECOND_UPLOAD_ATTEMPT = 2
FIRST_ATTEMPT_DID_NOT_RESUME = "first upload attempt did not resume"
SECOND_ATTEMPT_DID_NOT_START = "second upload attempt did not start"
UNEXPECTED_REPLAY_ATTEMPT = "unexpected upload replay attempt"


def sync_chunks(chunks: tuple[bytes, ...]) -> Iterator[bytes]:
    yield from chunks


async def async_chunks(chunks: tuple[bytes, ...]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        await asyncio.sleep(0)
        yield chunk


class SyncBodyFactory:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.calls = 0

    def __call__(self) -> Iterator[bytes]:
        self.calls += 1
        yield from self._chunks


class AsyncBodyFactory:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.calls = 0

    def __call__(self) -> AsyncIterator[bytes]:
        self.calls += 1
        return async_chunks(self._chunks)


class CoordinatedReplayBodyFactory:
    def __init__(self, expected_body: bytes, stale_body: bytes) -> None:
        self._expected_body = expected_body
        self._stale_body = stale_body
        self._lock = threading.Lock()
        self._second_started = threading.Event()
        self._stale_released = threading.Event()
        self.first_closed = threading.Event()
        self.second_closed = threading.Event()
        self.calls = 0

    def __call__(self) -> Iterator[bytes]:
        with self._lock:
            self.calls += 1
            attempt = self.calls
        if attempt == 1:
            return self._first_attempt()
        if attempt == SECOND_UPLOAD_ATTEMPT:
            return self._second_attempt()
        raise RuntimeError(UNEXPECTED_REPLAY_ATTEMPT)

    def _first_attempt(self) -> Iterator[bytes]:
        try:
            yield b"first-attempt-prefix"
            if not self._second_started.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(SECOND_ATTEMPT_DID_NOT_START)
            self._stale_released.set()
            yield self._stale_body
        finally:
            self.first_closed.set()

    def _second_attempt(self) -> Iterator[bytes]:
        try:
            self._second_started.set()
            if not self._stale_released.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(FIRST_ATTEMPT_DID_NOT_RESUME)
            yield self._expected_body
        finally:
            self.second_closed.set()


class FailOnReplayBodyFactory:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    def __call__(self) -> Iterator[bytes]:
        self.calls += 1
        if self.calls > 1:
            raise self._error
        return iter((b"initial-attempt",))


class FailingSyncBodyFactory:
    def __init__(self, message: str) -> None:
        self._message = message
        self.calls = 0

    def __call__(self) -> Iterator[bytes]:
        self.calls += 1
        yield b"partial"
        raise RuntimeError(self._message)
