__all__ = (
    "DelayedCloseEmptyFile",
    "FailingFilenoSeekableFile",
    "FailingSeekFile",
    "FailingTellFile",
    "FilenoOnly",
    "MisreportedLengthFile",
    "OversizedTellFile",
    "ProgressRawBody",
    "ReadOnlyFile",
    "RecordingRawUploadBody",
    "RetryingAsyncRawBody",
)

import asyncio
import io
import os
import time
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterator


NONEMPTY_PROGRESS_REQUIRED = "nonempty upload must use bounded progress"


class RetryingAsyncRawBody:
    def __init__(
        self,
        *,
        send_results: list[bool] | None = None,
        fail_results: list[bool] | None = None,
        closed: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self._send_results = iter(send_results or [])
        self._fail_results = iter(fail_results or [])
        self._closed = closed
        self.sent_chunks: list[bytes] = []
        self.final_chunks: list[bytes] = []
        self.failures: list[str] = []
        self.events = [] if events is None else events

    def send_nowait(self, chunk: bytes) -> bool:
        self.sent_chunks.append(chunk)
        return next(self._send_results)

    def send_final_nowait(self, chunk: bytes) -> bool:
        self.final_chunks.append(chunk)
        self.events.append("final")
        return next(self._send_results)

    def send_part_nowait(self, chunk: bytes, offset: int, *, final: bool = False) -> int:
        send = self.send_final_nowait if final else self.send_nowait
        return bytes.__len__(chunk) - offset if send(chunk) else 0

    def fail_nowait(self, message: str) -> bool:
        self.failures.append(message)
        self.events.append("fail")
        return next(self._fail_results)

    def finish(self) -> None:
        self.events.append("finish")

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True
        self.events.append("close")


class RecordingRawUploadBody:
    def __init__(
        self,
        _content_length: int | None,
        start_callback: object,
        _replayable: object,
        _ready_callback: object,
        *,
        raw_client: object | None = None,
    ) -> None:
        self.start_callback = start_callback
        self.raw_client = raw_client
        self.closed: bool = False

    def close(self) -> None:
        self.closed = True


class ProgressRawBody:
    def __init__(self, accepted: list[int], *, close_on_backpressure: bool = False) -> None:
        self._accepted = iter(accepted)
        self._close_on_backpressure = close_on_backpressure
        self.closed = False
        self.calls: list[tuple[bytes, int, bool]] = []
        self.received = bytearray()
        self.first_accepted = asyncio.Event()
        self.backpressure = asyncio.Event()

    def send_part_nowait(self, chunk: bytes, offset: int, *, final: bool = False) -> int:
        self.calls.append((chunk, offset, final))
        accepted = next(self._accepted)
        self.received.extend(chunk[offset : offset + accepted])
        if accepted:
            self.first_accepted.set()
        else:
            self.backpressure.set()
        if not accepted and self._close_on_backpressure:
            self.closed = True
        return accepted

    def send_nowait(self, chunk: bytes) -> bool:
        if chunk:
            raise AssertionError(NONEMPTY_PROGRESS_REQUIRED)
        return True

    def send_final_nowait(self, chunk: bytes) -> bool:
        if chunk:
            raise AssertionError(NONEMPTY_PROGRESS_REQUIRED)
        return True

    def fail_nowait(self, message: str) -> bool:
        raise AssertionError(message)

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class MisreportedLengthFile:
    def __init__(self, content: bytes, declared_length: int) -> None:
        self._declared_length = declared_length
        self._file = io.BytesIO(content)
        self._length_probe = False
        self.close_calls = 0

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def tell(self) -> int:
        if self._length_probe:
            return self._declared_length
        return self._file.tell()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_END:
            self._length_probe = True
            return self._declared_length
        self._length_probe = False
        return self._file.seek(offset, whence)

    def close(self) -> None:
        self.close_calls += 1
        self._file.close()


class DelayedCloseEmptyFile(io.BytesIO):
    def __init__(self, delay: float = 0.05) -> None:
        super().__init__()
        self._delay = delay

    def close(self) -> None:
        time.sleep(self._delay)
        super().close()


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
