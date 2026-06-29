__all__ = (
    "FailingFilenoSeekableFile",
    "FailingSeekFile",
    "FailingTellFile",
    "FilenoOnly",
    "OversizedTellFile",
    "ReadOnlyFile",
    "RetryingAsyncRawBody",
)

import io
import os
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator


class RetryingAsyncRawBody:
    def __init__(
        self,
        *,
        send_results: list[bool] | None = None,
        fail_results: list[bool] | None = None,
        closed: bool = False,
    ) -> None:
        self._send_results = iter(send_results or [])
        self._fail_results = iter(fail_results or [])
        self._closed = closed
        self.sent_chunks: list[bytes] = []
        self.failures: list[str] = []

    def send_nowait(self, chunk: bytes) -> bool:
        self.sent_chunks.append(chunk)
        return next(self._send_results)

    def fail_nowait(self, message: str) -> bool:
        self.failures.append(message)
        return next(self._fail_results)

    def is_closed(self) -> bool:
        return self._closed


class FilenoOnly:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd


class FailingTellFile(FilenoOnly):
    def tell(self) -> int:
        raise OSError


class OversizedTellFile(FilenoOnly):
    def tell(self) -> int:
        return 100


class FailingFilenoSeekableFile:
    def __init__(self, content: bytes) -> None:
        self._file = io.BytesIO(content)

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def fileno(self) -> int:
        raise OSError

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def __iter__(self) -> "Iterator[bytes]":
        yield from ()


class ReadOnlyFile:
    def read(self, _size: int = -1, /) -> bytes:
        return b""


class FailingSeekFile:
    def tell(self) -> int:
        return 0

    def seek(self, _offset: int, _whence: int = os.SEEK_SET) -> int:
        raise OSError
