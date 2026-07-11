__all__ = ("StreamResponse",)

from collections.abc import Iterator
from types import TracebackType

from foghttp._client.raw.errors import public_raw_error
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from foghttp._streaming.text.lines import (
    DEFAULT_MAX_STREAM_LINE_CHARS,
    iter_lines,
    validate_max_line_chars,
)
from foghttp._streaming.text.sync_chunks import iter_text_chunks
from foghttp.telemetry import TelemetryRequestOutcome

from .base import StreamResponseBase
from .constants import DEFAULT_STREAM_TEXT_ERRORS


class StreamResponse(StreamResponseBase):
    __module__ = "foghttp.stream_response"
    __slots__ = ()

    def __enter__(self) -> "StreamResponse":
        self._ensure_current_process()
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
        errors: str = DEFAULT_STREAM_TEXT_ERRORS,
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
        errors: str = DEFAULT_STREAM_TEXT_ERRORS,
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
                    self._finish_lifecycle_debug()
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
