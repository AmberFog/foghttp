from collections.abc import Iterator
from dataclasses import dataclass
import io
import os
import stat
from typing import cast


UPLOAD_CHUNK_SIZE = 65_536
_STANDARD_FILE_TYPES = (io.BytesIO, io.FileIO, io.BufferedReader, io.BufferedRandom)
_IO_METHODS = frozenset(("read", "readinto", "readall", "write", "tell", "seek", "fileno", "getbuffer"))


@dataclass(frozen=True, slots=True)
class FileUploadSource:
    file: object

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self.file.read(UPLOAD_CHUNK_SIZE)  # type: ignore[attr-defined]
            if not chunk:
                return
            yield chunk


def file_content_length(file: object) -> int | None:
    # Subclasses and instance overrides can return bytes unrelated to storage.
    if type(file) not in _STANDARD_FILE_TYPES or _IO_METHODS.intersection(vars(file)):  # noqa: WPS421, WPS516
        return None
    stream = cast("io.BytesIO | io.FileIO | io.BufferedReader | io.BufferedRandom", file)
    try:
        size = _standard_file_size(stream)
        if size is None:
            return None
        current = stream.tell()
    except (OSError, TypeError, ValueError):
        return None
    return size - current if size >= current else None


def _standard_file_size(file: io.BytesIO | io.FileIO | io.BufferedReader | io.BufferedRandom) -> int | None:
    if isinstance(file, io.BytesIO):
        current = file.tell()
        size = file.seek(0, io.SEEK_END)
        file.seek(current)
        return size
    raw = file if isinstance(file, io.FileIO) else file.raw
    # Buffered reads can flush pending output through a customized raw.write.
    if type(raw) is not io.FileIO or _IO_METHODS.intersection(vars(raw)):  # noqa: WPS421, WPS516
        return None
    file_stat = os.fstat(raw.fileno())
    return file_stat.st_size if stat.S_ISREG(file_stat.st_mode) else None
