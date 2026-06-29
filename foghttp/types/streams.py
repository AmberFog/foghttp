__all__ = (
    "AsyncByteStream",
    "AsyncByteStreamFactory",
    "BodyChunk",
    "SyncByteStream",
    "SyncByteStreamFactory",
)

from collections.abc import AsyncIterator, Iterator
from typing import Protocol, TypeAlias


BodyChunk: TypeAlias = bytes | bytearray | memoryview


class SyncByteStream(Protocol):
    def __iter__(self) -> Iterator[BodyChunk]: ...


class AsyncByteStream(Protocol):
    def __aiter__(self) -> AsyncIterator[BodyChunk]: ...


class SyncByteStreamFactory(Protocol):
    def __call__(self) -> SyncByteStream: ...


class AsyncByteStreamFactory(Protocol):
    def __call__(self) -> AsyncByteStream: ...
