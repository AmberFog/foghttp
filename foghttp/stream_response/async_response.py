__all__ = ("AsyncStreamResponse",)

import asyncio
from collections.abc import AsyncIterator
from types import TracebackType

from foghttp._client.raw.errors import public_raw_error
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from foghttp._streaming.text.async_chunks import aiter_text_chunks
from foghttp._streaming.text.lines import (
    DEFAULT_MAX_STREAM_LINE_CHARS,
    aiter_lines,
    validate_max_line_chars,
)
from foghttp.telemetry import TelemetryRequestOutcome

from .base import StreamResponseBase
from .constants import DEFAULT_STREAM_TEXT_ERRORS


class AsyncStreamResponse(StreamResponseBase):
    __module__ = "foghttp.stream_response"
    __slots__ = ()

    async def __aenter__(self) -> "AsyncStreamResponse":
        self._ensure_current_process()
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
        errors: str = DEFAULT_STREAM_TEXT_ERRORS,
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
        errors: str = DEFAULT_STREAM_TEXT_ERRORS,
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
                    self._finish_lifecycle_debug()
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


def _async_exit_outcome(exc_type: type[BaseException] | None) -> TelemetryRequestOutcome:
    if exc_type is not None and issubclass(exc_type, asyncio.CancelledError):
        return TelemetryRequestOutcome.CANCELLED
    return TelemetryRequestOutcome.CLOSED
