__all__ = (
    "DEFAULT_MAX_STREAM_LINE_CHARS",
    "aiter_lines",
    "iter_lines",
    "validate_max_line_chars",
)

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
import re

from ...errors import ResponseError
from .iterators import close_async_iterator, close_iterator


DEFAULT_MAX_STREAM_LINE_CHARS = 1024 * 1024
MAX_LINE_CHARS_INVALID = "max_line_chars must be greater than 0 or None"
_LINE_BREAK_PATTERN = re.compile(r"\r\n|\r|\n")


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
        close_iterator(text_chunks)


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
        await close_async_iterator(text_chunks)


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
        scan_end = len(text) - 1 if text.endswith("\r") else len(text)
        for line_break in _LINE_BREAK_PATTERN.finditer(text, text_start, scan_end):
            self._append_segment(text[segment_start : line_break.start()])
            yield self._take_line()
            segment_start = line_break.end()
        self._append_segment(text[segment_start:scan_end])
        if scan_end < len(text):
            self._deferred_cr = True

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
