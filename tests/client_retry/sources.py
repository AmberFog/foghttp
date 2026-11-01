__all__ = (
    "AsyncBodyFactory",
    "BlockedSyncBodySource",
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
import time


SOURCE_COORDINATION_TIMEOUT = 2.0
SECOND_UPLOAD_ATTEMPT = 2
FIRST_ATTEMPT_DID_NOT_RESUME = "first upload attempt did not resume"
FIRST_ATTEMPT_DID_NOT_START = "first upload attempt did not start"
BLOCKED_UPLOAD_DID_NOT_RELEASE = "blocked upload did not release"
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
    def __init__(
        self,
        expected_body: bytes,
        stale_body: bytes,
        *,
        first_start: threading.Event | None = None,
    ) -> None:
        self._expected_body = expected_body
        self._stale_body = stale_body
        self._first_start = first_start
        self._lock = threading.Lock()
        self._events: list[tuple[str, int]] = []
        self.first_waiting = threading.Event()
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

    def snapshot_events(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(self._events)

    def _record_event(self, name: str) -> None:
        with self._lock:
            self._events.append((name, time.monotonic_ns()))

    def _first_attempt(self) -> Iterator[bytes]:
        try:
            if self._first_start is not None and not self._first_start.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(FIRST_ATTEMPT_DID_NOT_START)
            self._record_event("first_started")
            yield b"first-attempt-prefix"
            self._record_event("first_waiting")
            self.first_waiting.set()
            if not self._second_started.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(SECOND_ATTEMPT_DID_NOT_START)
            self._record_event("stale_released")
            self._stale_released.set()
            yield self._stale_body
        finally:
            self._record_event("first_closed")
            self.first_closed.set()

    def _second_attempt(self) -> Iterator[bytes]:
        try:
            self._record_event("second_started")
            self._second_started.set()
            if not self._stale_released.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(FIRST_ATTEMPT_DID_NOT_RESUME)
            yield self._expected_body
        finally:
            self._record_event("second_closed")
            self.second_closed.set()


class BlockedSyncBodySource:
    def __init__(self, prefix: bytes, *, first_start: threading.Event | None = None) -> None:
        self._prefix = prefix
        self._first_start = first_start
        self._lock = threading.Lock()
        self._events: list[tuple[str, int]] = []
        self.first_waiting = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()

    def __iter__(self) -> Iterator[bytes]:
        try:
            if self._first_start is not None and not self._first_start.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(FIRST_ATTEMPT_DID_NOT_START)
            self._record_event("first_started")
            yield self._prefix
            self._record_event("first_waiting")
            self.first_waiting.set()
            if not self.release.wait(SOURCE_COORDINATION_TIMEOUT):
                raise RuntimeError(BLOCKED_UPLOAD_DID_NOT_RELEASE)
        finally:
            self._record_event("closed")
            self.closed.set()

    def close(self) -> None:
        self._record_event("release")
        self.release.set()

    def snapshot_events(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(self._events)

    def _record_event(self, name: str) -> None:
        with self._lock:
            self._events.append((name, time.monotonic_ns()))


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
