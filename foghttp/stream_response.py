__all__ = ("AsyncStreamResponse", "StreamResponse")

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from types import TracebackType

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ._client.raw.errors import raise_public_raw_error
from ._redaction import redact_url
from ._response.encoding import response_encoding
from ._response.status import (
    is_client_error_status,
    is_error_status,
    is_redirect_status,
    is_server_error_status,
    is_success_status,
)
from ._streaming.text.async_chunks import aiter_text_chunks
from ._streaming.text.lines import (
    DEFAULT_MAX_STREAM_LINE_CHARS,
    aiter_lines,
    iter_lines,
    validate_max_line_chars,
)
from ._streaming.text.sync_chunks import iter_text_chunks
from .errors import HTTPStatusError, LifecycleError
from .headers import Headers
from .messages import (
    STREAM_RESPONSE_BODY_CONSUMED,
    STREAM_RESPONSE_CLOSED,
    http_status_error,
)
from .request_info import RequestInfo
from .response import Response


@dataclass(slots=True)
class _StreamResponseBase:
    status_code: int
    headers: Headers
    url: str
    request: RequestInfo
    http_version: str
    elapsed: float
    _raw: _foghttp.RawStreamResponse = field(repr=False)
    history: tuple[Response, ...] = ()
    _closed: bool = field(default=False, init=False, repr=False)
    _body_started: bool = field(default=False, init=False, repr=False)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"status_code={self.status_code!r}, "
            f"headers={self.headers!r}, "
            f"url={redact_url(self.url)!r}, "
            f"request={self.request!r}, "
            f"http_version={self.http_version!r}, "
            f"elapsed={self.elapsed!r}, "
            f"history=<{len(self.history)} responses>)"
        )

    @property
    def is_success(self) -> bool:
        return is_success_status(self.status_code)

    @property
    def is_redirect(self) -> bool:
        return is_redirect_status(self.status_code)

    @property
    def is_client_error(self) -> bool:
        return is_client_error_status(self.status_code)

    @property
    def is_server_error(self) -> bool:
        return is_server_error_status(self.status_code)

    @property
    def is_error(self) -> bool:
        return is_error_status(self.status_code)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._raw.close()

    @property
    def encoding(self) -> str:
        return response_encoding(self.headers, b"")

    def raise_for_status(self) -> None:
        if self.is_error:
            raise HTTPStatusError(
                http_status_error(
                    self.request.method,
                    self.request.url,
                    self.status_code,
                ),
                response=self,
            )

    def _start_body_iteration(self) -> None:
        if self._body_started:
            raise LifecycleError(STREAM_RESPONSE_BODY_CONSUMED)
        if self._closed:
            raise LifecycleError(STREAM_RESPONSE_CLOSED)
        self._body_started = True

    def _text_encoding(self, encoding: str | None) -> str:
        return self.encoding if encoding is None else encoding


class StreamResponse(_StreamResponseBase):
    __slots__ = ()

    def __enter__(self) -> "StreamResponse":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def iter_bytes(self) -> Iterator[bytes]:
        self._start_body_iteration()
        return self._iter_bytes()

    def iter_text(
        self,
        *,
        encoding: str | None = None,
        errors: str = "replace",
    ) -> Iterator[str]:
        self._start_body_iteration()
        return iter_text_chunks(
            self._iter_bytes(),
            encoding=self._text_encoding(encoding),
            errors=errors,
            close=self.close,
        )

    def iter_lines(
        self,
        *,
        encoding: str | None = None,
        errors: str = "replace",
        max_line_chars: int | None = DEFAULT_MAX_STREAM_LINE_CHARS,
    ) -> Iterator[str]:
        max_line_chars = validate_max_line_chars(max_line_chars)
        self._start_body_iteration()
        return iter_lines(
            iter_text_chunks(
                self._iter_bytes(),
                encoding=self._text_encoding(encoding),
                errors=errors,
                close=self.close,
            ),
            max_line_chars=max_line_chars,
        )

    def _iter_bytes(self) -> Iterator[bytes]:
        try:
            while True:
                chunk = self._next_chunk()
                if chunk is None:
                    self._closed = True
                    return
                yield chunk
        finally:
            if not self._closed:
                self.close()

    def _next_chunk(self) -> bytes | None:
        try:
            return self._raw.next_chunk()
        except _foghttp.FogHttpError as exc:
            self.close()
            raise_public_raw_error(exc)


class AsyncStreamResponse(_StreamResponseBase):
    __slots__ = ()

    async def __aenter__(self) -> "AsyncStreamResponse":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        self._start_body_iteration()
        return self._aiter_bytes()

    def aiter_text(
        self,
        *,
        encoding: str | None = None,
        errors: str = "replace",
    ) -> AsyncIterator[str]:
        self._start_body_iteration()
        return aiter_text_chunks(
            self._aiter_bytes(),
            encoding=self._text_encoding(encoding),
            errors=errors,
            close=self.close,
        )

    def aiter_lines(
        self,
        *,
        encoding: str | None = None,
        errors: str = "replace",
        max_line_chars: int | None = DEFAULT_MAX_STREAM_LINE_CHARS,
    ) -> AsyncIterator[str]:
        max_line_chars = validate_max_line_chars(max_line_chars)
        self._start_body_iteration()
        return aiter_lines(
            aiter_text_chunks(
                self._aiter_bytes(),
                encoding=self._text_encoding(encoding),
                errors=errors,
                close=self.close,
            ),
            max_line_chars=max_line_chars,
        )

    async def aclose(self) -> None:
        self.close()

    async def _aiter_bytes(self) -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await self._next_chunk()
                if chunk is None:
                    self._closed = True
                    return
                yield chunk
        finally:
            if not self._closed:
                self.close()

    async def _next_chunk(self) -> bytes | None:
        try:
            return await self._raw.next_chunk_async()
        except _foghttp.FogHttpError as exc:
            self.close()
            raise_public_raw_error(exc)
