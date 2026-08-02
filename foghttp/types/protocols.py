__all__ = (
    "AsyncStreamResponseProtocol",
    "BufferedResponseProtocol",
    "RequestProtocol",
    "ResponseProtocol",
    "StreamResponseProtocol",
)

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, Protocol


if TYPE_CHECKING:
    from foghttp.headers import Headers
    from foghttp.request_extensions import RequestExtensions
    from foghttp.retry_trace import RetryTrace


class RequestProtocol(Protocol):
    """Stable request metadata shared by prepared and completed requests."""

    @property
    def method(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def headers(self) -> "Headers": ...

    @property
    def extensions(self) -> "RequestExtensions": ...


class _ResponseMetadataProtocol(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> "Headers": ...

    @property
    def url(self) -> str: ...

    @property
    def request(self) -> RequestProtocol: ...

    @property
    def http_version(self) -> str: ...

    @property
    def elapsed(self) -> float: ...

    @property
    def history(self) -> tuple["BufferedResponseProtocol", ...]: ...


class _ResponseStatusProtocol(Protocol):
    @property
    def is_success(self) -> bool: ...

    @property
    def is_redirect(self) -> bool: ...

    @property
    def is_client_error(self) -> bool: ...

    @property
    def is_server_error(self) -> bool: ...

    @property
    def is_error(self) -> bool: ...

    def raise_for_status(self) -> None: ...


class ResponseProtocol(_ResponseMetadataProtocol, _ResponseStatusProtocol, Protocol):
    """Stable metadata and status behavior shared by all response modes."""

    @property
    def retry_trace(self) -> "RetryTrace | None": ...

    @property
    def encoding(self) -> str: ...


class BufferedResponseProtocol(ResponseProtocol, Protocol):
    """Stable buffered-response body behavior."""

    @property
    def content(self) -> bytes: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


class StreamResponseProtocol(ResponseProtocol, Protocol):
    """Stable synchronous streaming-response behavior."""

    def close(self) -> None: ...

    def iter_bytes(self) -> Iterator[bytes]: ...

    def iter_text(
        self,
        *,
        encoding: str | None = ...,
        errors: str = ...,
    ) -> Iterator[str]: ...

    def iter_lines(
        self,
        *,
        encoding: str | None = ...,
        errors: str = ...,
        max_line_chars: int | None = ...,
    ) -> Iterator[str]: ...


class AsyncStreamResponseProtocol(ResponseProtocol, Protocol):
    """Stable asynchronous streaming-response behavior."""

    def close(self) -> None: ...

    async def aclose(self) -> None: ...

    def aiter_bytes(self) -> AsyncIterator[bytes]: ...

    def aiter_text(
        self,
        *,
        encoding: str | None = ...,
        errors: str = ...,
    ) -> AsyncIterator[str]: ...

    def aiter_lines(
        self,
        *,
        encoding: str | None = ...,
        errors: str = ...,
        max_line_chars: int | None = ...,
    ) -> AsyncIterator[str]: ...
