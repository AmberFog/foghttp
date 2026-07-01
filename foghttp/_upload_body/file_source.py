from collections.abc import Iterator
from dataclasses import dataclass
import os
import stat


UPLOAD_CHUNK_SIZE = 65_536


@dataclass(frozen=True, slots=True)
class FileUploadSource:
    file: object

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self.file.read(UPLOAD_CHUNK_SIZE)  # type: ignore[attr-defined]
            if not chunk:
                return
            yield chunk


@dataclass(frozen=True, slots=True)
class FileDescriptorLength:
    checked: bool
    value: int | None


def file_content_length(file: object) -> int | None:
    descriptor_length = _file_descriptor_remaining_size(file)
    if descriptor_length.checked:
        return descriptor_length.value
    return _seekable_remaining_size(file)


def _file_descriptor_remaining_size(file: object) -> FileDescriptorLength:
    file_stat = _file_descriptor_stat(file)
    if file_stat is None:
        return FileDescriptorLength(checked=False, value=None)
    if not stat.S_ISREG(file_stat.st_mode):
        return FileDescriptorLength(checked=True, value=None)
    return FileDescriptorLength(
        checked=True,
        value=_regular_file_remaining_size(file, file_stat.st_size),
    )


def _file_descriptor_stat(file: object) -> "os.stat_result | None":
    fileno = getattr(file, "fileno", None)
    if not callable(fileno):
        return None
    try:
        return os.fstat(fileno())
    except (OSError, TypeError, ValueError):
        return None


def _regular_file_remaining_size(file: object, size: int) -> int | None:
    tell = getattr(file, "tell", None)
    if not callable(tell):
        return None
    try:
        current = int(tell())
    except (OSError, TypeError, ValueError):
        return None
    return size - current if size >= current else None


def _seekable_remaining_size(file: object) -> int | None:
    tell = getattr(file, "tell", None)
    seek = getattr(file, "seek", None)
    if not callable(tell) or not callable(seek):
        return None
    try:
        current = int(tell())
        seek(0, os.SEEK_END)
        end = int(tell())
        seek(current, os.SEEK_SET)
    except (OSError, TypeError, ValueError):
        return None
    return end - current if end >= current else None
