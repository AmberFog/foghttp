__all__ = (
    "DEFAULT_MAX_STREAM_LINE_CHARS",
    "aiter_lines",
    "aiter_text_chunks",
    "iter_lines",
    "iter_text_chunks",
    "validate_max_line_chars",
)

import codecs
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..errors import ResponseError


DEFAULT_MAX_STREAM_LINE_CHARS = 1024 * 1024
MAX_LINE_CHARS_INVALID = "max_line_chars must be greater than 0 or None"


@runtime_checkable
class _ClosableIterator(Protocol):
    def close(self) -> None: ...


@runtime_checkable
class _AsyncClosableIterator(Protocol):
    async def aclose(self) -> None: ...


def iter_text_chunks(
    byte_chunks: Iterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: Callable[[], None] | None = None,
) -> Iterator[str]:
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
        for chunk in byte_chunks:
            if text := decoder.decode(chunk):
                yield text
        if text := decoder.decode(b"", final=True):
            yield text
    finally:
        if close is not None:
            close()
        _close_iterator(byte_chunks)


async def aiter_text_chunks(
    byte_chunks: AsyncIterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
        async for chunk in byte_chunks:
            if text := decoder.decode(chunk):
                yield text
        if text := decoder.decode(b"", final=True):
            yield text
    finally:
        if close is not None:
            close()
        await _close_async_iterator(byte_chunks)


def iter_lines(
    text_chunks: Iterator[str],
    *,
    max_line_chars: int | None = DEFAULT_MAX_STREAM_LINE_CHARS,
) -> Iterator[str]:
    splitter = _LineSplitter(max_line_chars=max_line_chars)
    try:
        for chunk in text_chunks:
            yield from splitter.feed(chunk)
        yield from splitter.flush()
    finally:
        _close_iterator(text_chunks)


async def aiter_lines(
    text_chunks: AsyncIterator[str],
    *,
    max_line_chars: int | None = DEFAULT_MAX_STREAM_LINE_CHARS,
) -> AsyncIterator[str]:
    splitter = _LineSplitter(max_line_chars=max_line_chars)
    try:
        async for chunk in text_chunks:
            for line in splitter.feed(chunk):
                yield line
        for line in splitter.flush():
            yield line
    finally:
        await _close_async_iterator(text_chunks)


@dataclass(slots=True)
class _LineSplitter:
    max_line_chars: int | None
    _pending: str = field(default="", init=False)

    def feed(self, text: str) -> Iterator[str]:
        if text:
            self._pending += text
            yield from self._complete_lines()

    def flush(self) -> Iterator[str]:
        yield from self._complete_lines(final=True)
        if self._pending:
            yield self._pending
            self._pending = ""

    def _complete_lines(self, *, final: bool = False) -> Iterator[str]:
        while self._pending:
            line_end = _first_line_end(self._pending)
            if line_end is None:
                _ensure_max_line_chars(len(self._pending), self.max_line_chars)
                return
            _ensure_max_line_chars(line_end, self.max_line_chars)
            if _line_end_is_deferred_cr(self._pending, line_end, final=final):
                return

            delimiter_size = _line_delimiter_size(self._pending, line_end)
            yield self._pending[:line_end]
            self._pending = self._pending[line_end + delimiter_size :]


def _first_line_end(text: str) -> int | None:
    newline_index = text.find("\n")
    carriage_return_index = text.find("\r")
    if newline_index == -1:
        return None if carriage_return_index == -1 else carriage_return_index
    if carriage_return_index == -1:
        return newline_index
    return min(newline_index, carriage_return_index)


def _line_end_is_deferred_cr(text: str, line_end: int, *, final: bool) -> bool:
    return not final and text[line_end] == "\r" and line_end == len(text) - 1


def _line_delimiter_size(text: str, line_end: int) -> int:
    if text[line_end : line_end + 2] == "\r\n":
        return 2
    return 1


def validate_max_line_chars(max_line_chars: int | None) -> int | None:
    if max_line_chars is None or max_line_chars > 0:
        return max_line_chars
    raise ValueError(MAX_LINE_CHARS_INVALID)


def _line_too_long(max_line_chars: int) -> ResponseError:
    return ResponseError(f"stream line exceeded max_line_chars={max_line_chars}")


def _ensure_max_line_chars(line_chars: int, max_line_chars: int | None) -> None:
    if max_line_chars is not None and line_chars > max_line_chars:
        raise _line_too_long(max_line_chars)


def _close_iterator(iterator: Iterator[object]) -> None:
    if isinstance(iterator, _ClosableIterator):
        iterator.close()


async def _close_async_iterator(iterator: AsyncIterator[object]) -> None:
    if isinstance(iterator, _AsyncClosableIterator):
        await iterator.aclose()
