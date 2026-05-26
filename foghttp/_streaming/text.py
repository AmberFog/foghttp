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
    _pending_parts: list[str] = field(default_factory=list, init=False)
    _pending_chars: int = field(default=0, init=False)
    _deferred_cr: bool = field(default=False, init=False)

    def feed(self, text: str) -> Iterator[str]:
        if not text:
            return

        text_start = 0
        if self._deferred_cr:
            self._deferred_cr = False
            yield self._take_line()
            if text.startswith("\n"):
                text_start = 1

        segment_start = text_start
        char_index = text_start
        while char_index < len(text):
            char = text[char_index]
            if char == "\n":
                self._append_segment(text[segment_start:char_index])
                yield self._take_line()
                char_index += 1
                segment_start = char_index
                continue
            if char == "\r":
                self._append_segment(text[segment_start:char_index])
                next_index = char_index + 1
                if next_index == len(text):
                    self._deferred_cr = True
                    return
                yield self._take_line()
                char_index = next_index + 1 if text[next_index] == "\n" else next_index
                segment_start = char_index
                continue
            char_index += 1

        self._append_segment(text[segment_start:])

    def flush(self) -> Iterator[str]:
        if self._deferred_cr:
            self._deferred_cr = False
            yield self._take_line()
        if self._pending_parts:
            yield self._take_line()

    def _append_segment(self, segment: str) -> None:
        if not segment:
            return
        next_line_chars = self._pending_chars + len(segment)
        _ensure_max_line_chars(next_line_chars, self.max_line_chars)
        self._pending_parts.append(segment)
        self._pending_chars = next_line_chars

    def _take_line(self) -> str:
        line = "".join(self._pending_parts)
        self._pending_parts.clear()
        self._pending_chars = 0
        return line


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
