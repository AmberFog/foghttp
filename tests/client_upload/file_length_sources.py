from __future__ import annotations

from contextlib import contextmanager
import io
from typing import TYPE_CHECKING
from unittest.mock import patch


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO


FILE_PAYLOAD = b"file upload payload"
STANDARD_SOURCE_KINDS = ("bytesio", "raw", "buffered_reader", "buffered_random")


@contextmanager
def standard_file(tmp_path: Path, source_kind: str) -> Iterator[BinaryIO]:
    path = tmp_path / "standard-file.bin"
    path.write_bytes(FILE_PAYLOAD)
    if source_kind == "bytesio":
        source = io.BytesIO(FILE_PAYLOAD)
    elif source_kind == "raw":
        source = path.open("rb", buffering=0)
    elif source_kind == "buffered_reader":
        source = path.open("rb")
    elif source_kind == "buffered_random":
        source = path.open("r+b")
    else:
        raise ValueError(source_kind)
    with source:
        yield source


@contextmanager
def buffered_write_source(path: Path, payload: bytes = FILE_PAYLOAD) -> Iterator[io.BufferedRandom]:
    path.write_bytes(payload)
    with path.open("r+b", buffering=0) as raw:
        original_write = raw.write

        def expanding_write(chunk: bytes) -> int:
            original_write(bytes(chunk) * 2)
            raw.seek(-len(chunk), io.SEEK_CUR)
            return len(chunk)

        with patch.object(raw, "write", expanding_write), io.BufferedRandom(raw) as source:
            source.write(payload)
            yield source


class GuardedFile:
    def __init__(self) -> None:
        self._buffer = io.BytesIO(FILE_PAYLOAD)
        self.read_calls = 0

    @property
    def position(self) -> int:
        return self._buffer.tell()

    def read(self, size: int = -1, /) -> bytes:
        self.read_calls += 1
        return self._buffer.read(size)

    def fileno(self) -> int:
        raise AssertionError

    def tell(self) -> int:
        raise AssertionError

    def seek(self, _offset: int, _whence: int = io.SEEK_SET) -> int:
        raise AssertionError


class ExpandingBytesIO(io.BytesIO):
    def read(self, size: int = -1, /) -> bytes:
        return super().read(size) * 2


def expanding_readinto(source: BinaryIO, buffer: bytearray) -> int:
    chunk = source.read(len(buffer) // 2) * 2
    buffer[: len(chunk)] = chunk
    return len(chunk)


class ExpandingFileIO(io.FileIO):
    def readinto(self, buffer: bytearray) -> int:
        return expanding_readinto(self, buffer)
