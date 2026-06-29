__all__ = (
    "AsyncMultipartFileContent",
    "AsyncMultipartFileTuple",
    "AsyncMultipartFileValue",
    "AsyncMultipartFiles",
    "BinaryFile",
    "SyncMultipartFileContent",
    "SyncMultipartFileTuple",
    "SyncMultipartFileValue",
    "SyncMultipartFiles",
)

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeAlias

from .streams import (
    AsyncByteStream,
    AsyncByteStreamFactory,
    SyncByteStream,
    SyncByteStreamFactory,
)


class BinaryFile(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


SyncMultipartFileContent: TypeAlias = bytes | BinaryFile | SyncByteStream | SyncByteStreamFactory
SyncMultipartFileTuple: TypeAlias = tuple[str, SyncMultipartFileContent] | tuple[str, SyncMultipartFileContent, str]
SyncMultipartFileValue: TypeAlias = SyncMultipartFileContent | SyncMultipartFileTuple
SyncMultipartFiles: TypeAlias = Mapping[str, SyncMultipartFileValue] | Sequence[tuple[str, SyncMultipartFileValue]]

AsyncMultipartFileContent: TypeAlias = bytes | BinaryFile | AsyncByteStream | AsyncByteStreamFactory
AsyncMultipartFileTuple: TypeAlias = tuple[str, AsyncMultipartFileContent] | tuple[str, AsyncMultipartFileContent, str]
AsyncMultipartFileValue: TypeAlias = AsyncMultipartFileContent | AsyncMultipartFileTuple
AsyncMultipartFiles: TypeAlias = Mapping[str, AsyncMultipartFileValue] | Sequence[tuple[str, AsyncMultipartFileValue]]
