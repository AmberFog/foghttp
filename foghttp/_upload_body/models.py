from typing import TYPE_CHECKING, Protocol, TypeAlias

from ..types import (
    AsyncByteStream,
    AsyncByteStreamFactory,
    BinaryFile,
    SyncByteStream,
    SyncByteStreamFactory,
)


if TYPE_CHECKING:
    from foghttp import _foghttp


SyncRequestContent: TypeAlias = bytes | str | BinaryFile | SyncByteStream | SyncByteStreamFactory
AsyncRequestContent: TypeAlias = (
    bytes | str | BinaryFile | SyncByteStream | AsyncByteStream | SyncByteStreamFactory | AsyncByteStreamFactory
)


class SyncUploadBody(Protocol):
    @property
    def buffered_body(self) -> bytes | None: ...

    @property
    def raw_body(self) -> "_foghttp.RawUploadBody | None": ...

    def close(self) -> None: ...


class AsyncUploadBody(Protocol):
    @property
    def buffered_body(self) -> bytes | None: ...

    @property
    def raw_body(self) -> "_foghttp.RawUploadBody | None": ...

    async def aclose(self) -> None: ...
