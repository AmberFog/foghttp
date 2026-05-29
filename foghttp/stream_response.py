__all__ = ("AsyncStreamResponse", "StreamResponse")

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from types import TracebackType

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ._client.raw.errors import public_raw_error
from ._client.telemetry import TelemetryRequestContext, elapsed_seconds_to_ns
from ._client.telemetry.emission import TelemetryCompletion, TelemetryResponseMetadata
from ._client.telemetry.url import (
    redacted_url as telemetry_redacted_url,
    url_origin,
)
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
from .telemetry import TelemetryRequestOutcome


_DEFAULT_STREAM_TEXT_ERRORS = "replace"


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
    _telemetry_context: TelemetryRequestContext | None = field(default=None, init=False, repr=False)
    _telemetry_finished: bool = field(default=False, init=False, repr=False)

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

    @property
    def encoding(self) -> str:
        return response_encoding(self.headers, b"")

    def close(self) -> None:
        self._close(
            outcome=TelemetryRequestOutcome.CLOSED,
            suppress_telemetry_errors=False,
        )

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

    def _close(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_telemetry_errors: bool,
    ) -> None:
        if self._closed:
            return
        self._closed = True
        self._raw.close()
        self._finish_telemetry(
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_telemetry_errors,
        )

    def _start_body_iteration(self) -> None:
        if self._body_started:
            raise LifecycleError(STREAM_RESPONSE_BODY_CONSUMED)
        if self._closed:
            raise LifecycleError(STREAM_RESPONSE_CLOSED)
        self._body_started = True

    def _text_encoding(self, encoding: str | None) -> str:
        return self.encoding if encoding is None else encoding

    def _finish_telemetry(
        self,
        *,
        outcome: TelemetryRequestOutcome,
        error: BaseException | None = None,
        suppress_hook_errors: bool = False,
    ) -> None:
        if self._telemetry_context is None or self._telemetry_finished:
            return

        self._telemetry_finished = True
        completion = TelemetryCompletion(
            response=self._telemetry_response_metadata(),
            outcome=outcome,
            error=error,
            suppress_hook_errors=suppress_hook_errors,
        )
        self._telemetry_context.response_body_finished(completion)
        self._telemetry_context.request_finished(completion)

    def _telemetry_response_metadata(self) -> TelemetryResponseMetadata:
        return TelemetryResponseMetadata(
            status_code=self.status_code,
            elapsed_ns=elapsed_seconds_to_ns(self.elapsed),
            origin=url_origin(self.url),
            redacted_url=telemetry_redacted_url(self.url),
        )


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
        self._close(
            outcome=TelemetryRequestOutcome.CLOSED,
            suppress_telemetry_errors=exc_type is not None,
        )

    def iter_bytes(self) -> Iterator[bytes]:
        self._start_body_iteration()
        return self._iter_bytes()

    def iter_text(
        self,
        *,
        encoding: str | None = None,
        errors: str = _DEFAULT_STREAM_TEXT_ERRORS,
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
        errors: str = _DEFAULT_STREAM_TEXT_ERRORS,
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
                    self._finish_telemetry(outcome=TelemetryRequestOutcome.SUCCESS)
                    return
                yield chunk
        finally:
            if not self._closed:
                self._close(
                    outcome=TelemetryRequestOutcome.CLOSED,
                    suppress_telemetry_errors=True,
                )

    def _next_chunk(self) -> bytes | None:
        try:
            return self._raw.next_chunk()
        except _foghttp.FogHttpError as raw_error:
            public_error = public_raw_error(raw_error)
            self._close(
                outcome=TelemetryRequestOutcome.ERROR,
                error=public_error,
                suppress_telemetry_errors=True,
            )
            raise public_error from raw_error


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
        outcome = _async_exit_outcome(exc_type)
        self._close(
            outcome=outcome,
            error=exc if outcome is TelemetryRequestOutcome.CANCELLED else None,
            suppress_telemetry_errors=exc_type is not None,
        )

    def aiter_bytes(self) -> AsyncIterator[bytes]:
        self._start_body_iteration()
        return self._aiter_bytes()

    def aiter_text(
        self,
        *,
        encoding: str | None = None,
        errors: str = _DEFAULT_STREAM_TEXT_ERRORS,
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
        errors: str = _DEFAULT_STREAM_TEXT_ERRORS,
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
                    self._finish_telemetry(outcome=TelemetryRequestOutcome.SUCCESS)
                    return
                yield chunk
        except asyncio.CancelledError as cancelled_error:
            self._close(
                outcome=TelemetryRequestOutcome.CANCELLED,
                error=cancelled_error,
                suppress_telemetry_errors=True,
            )
            raise
        finally:
            if not self._closed:
                self._close(
                    outcome=TelemetryRequestOutcome.CLOSED,
                    suppress_telemetry_errors=True,
                )

    async def _next_chunk(self) -> bytes | None:
        try:
            return await self._raw.next_chunk_async()
        except _foghttp.FogHttpError as raw_error:
            public_error = public_raw_error(raw_error)
            self._close(
                outcome=TelemetryRequestOutcome.ERROR,
                error=public_error,
                suppress_telemetry_errors=True,
            )
            raise public_error from raw_error


def bind_stream_telemetry(
    response: _StreamResponseBase,
    telemetry_context: TelemetryRequestContext,
) -> None:
    object.__setattr__(response, "_telemetry_context", telemetry_context)


def _async_exit_outcome(exc_type: type[BaseException] | None) -> TelemetryRequestOutcome:
    if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
        return TelemetryRequestOutcome.CANCELLED
    return TelemetryRequestOutcome.CLOSED
