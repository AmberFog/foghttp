__all__ = (
    "AsyncChunks",
    "BlockingAsyncChunks",
    "BlockingSyncChunks",
    "CallableAsyncChunks",
    "CallableSyncChunks",
    "ClosingBytesFile",
    "FailsWhenReadPastExactLengthFile",
    "NonRegularFilenoFile",
    "SyncChunks",
    "ThreadTrackingSyncChunks",
    "TrackedFactory",
)

import asyncio
from collections.abc import Callable
import io
import os
import threading
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


class ClosingBytesFile:
    def __init__(self, content: bytes, *, name: str = "payload.bin") -> None:
        self._file = io.BytesIO(content)
        self.name = name
        self.closed: bool = False
        self.close_calls = 0
        self.read_sizes: list[int] = []

    def read(self, size: int = -1, /) -> bytes:
        self.read_sizes.append(size)
        return self._file.read(size)

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self._file.close()


class FailsWhenReadPastExactLengthFile:
    def __init__(self, content: bytes) -> None:
        self._file = io.BytesIO(content)
        self._read_calls = 0
        self.read_past_declared_body = False
        self.closed: bool = False
        self.close_calls = 0

    def read(self, size: int = -1, /) -> bytes:
        self._read_calls += 1
        if self._read_calls == 1:
            return self._file.read(size)
        self.read_past_declared_body = True
        raise RuntimeError

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_calls += 1
        self._file.close()


class SyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.closed: bool = False
        self.close_calls = 0

    def __iter__(self) -> "Iterator[bytes]":
        yield from self._chunks

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class CallableSyncChunks(SyncChunks):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        super().__init__(chunks)
        self.calls = 0

    def __call__(self) -> SyncChunks:
        self.calls += 1
        return SyncChunks((b"factory-product",))


class BlockingSyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.started = threading.Event()
        self.finished = threading.Event()
        self.release = threading.Event()
        self.closed: bool = False
        self.close_calls = 0

    def __iter__(self) -> "Iterator[bytes]":
        try:
            self.started.set()
            for chunk in self._chunks:
                yield chunk
                self.release.wait()
                if self.closed:
                    return
        finally:
            self.finished.set()

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.release.set()


class BlockingAsyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = asyncio.Event()
        self.closed: bool = False
        self.close_calls = 0

    def __aiter__(self) -> "AsyncIterator[bytes]":
        return self._iterate()

    async def _iterate(self) -> "AsyncIterator[bytes]":
        try:
            self.started.set()
            for chunk in self._chunks:
                yield chunk
                await self.release.wait()
                if self.closed:
                    return
        finally:
            self.finished.set()

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.release.set()


class ThreadTrackingSyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.thread_ids: list[int] = []
        self.close_thread_ids: list[int] = []

    def __iter__(self) -> "Iterator[bytes]":
        self.thread_ids.append(threading.get_ident())
        yield from self._chunks

    def close(self) -> None:
        self.close_thread_ids.append(threading.get_ident())


class NonRegularFilenoFile:
    def __init__(self, content: bytes, *, name: str = "payload.bin") -> None:
        self._file = io.BytesIO(content)
        self._read_fd, self._write_fd = os.pipe()
        self.name = name
        self.closed: bool = False

    def __enter__(self) -> "NonRegularFilenoFile":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def fileno(self) -> int:
        return self._read_fd

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._file.close()
        os.close(self._read_fd)
        os.close(self._write_fd)


class AsyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.closed: bool = False
        self.close_calls = 0

    def __aiter__(self) -> "AsyncIterator[bytes]":
        return self._iterate()

    async def _iterate(self) -> "AsyncIterator[bytes]":
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk

    async def aclose(self) -> None:
        self.close_calls += 1
        self.closed = True


class CallableAsyncChunks(AsyncChunks):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        super().__init__(chunks)
        self.calls = 0

    def __call__(self) -> AsyncChunks:
        self.calls += 1
        return AsyncChunks((b"factory-product",))


class TrackedFactory:
    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory
        self.calls = 0
        self.close_calls = 0

    def __call__(self) -> object:
        self.calls += 1
        return self._factory()

    def close(self) -> None:
        self.close_calls += 1
