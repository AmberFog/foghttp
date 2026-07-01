__all__ = (
    "AsyncChunks",
    "BlockingSyncChunks",
    "ClosingBytesFile",
    "NonRegularFilenoFile",
    "SyncChunks",
    "ThreadTrackingSyncChunks",
)

import asyncio
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

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        self.closed = True
        self._file.close()


class SyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.closed: bool = False

    def __iter__(self) -> "Iterator[bytes]":
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class BlockingSyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.started = threading.Event()
        self.finished = threading.Event()
        self.release = threading.Event()
        self.closed: bool = False

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
        self.closed = True
        self.release.set()


class ThreadTrackingSyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.thread_ids: list[int] = []

    def __iter__(self) -> "Iterator[bytes]":
        self.thread_ids.append(threading.get_ident())
        yield from self._chunks


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

    def __aiter__(self) -> "AsyncIterator[bytes]":
        return self._iterate()

    async def _iterate(self) -> "AsyncIterator[bytes]":
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True
