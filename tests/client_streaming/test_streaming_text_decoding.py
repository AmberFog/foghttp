from collections.abc import AsyncIterator

import pytest

import foghttp
from foghttp._streaming.text.async_chunks import aiter_text_chunks
from foghttp._streaming.text.lines import aiter_lines, iter_lines
from foghttp._streaming.text.sync_chunks import iter_text_chunks
from tests.client_streaming.text_decoding_sources import (
    AsyncClosableByteIterator,
    ClosableByteIterator,
)


def test_streaming_line_decoder_ignores_empty_byte_chunks() -> None:
    byte_chunks = iter((b"", b"alpha\n", b"", b"beta"))
    text_chunks = iter_text_chunks(byte_chunks, encoding="utf-8", errors="replace")

    assert list(iter_lines(text_chunks)) == ["alpha", "beta"]


def test_streaming_line_decoder_rejects_overlong_line() -> None:
    with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
        list(iter_lines(iter(("alpha",)), max_line_chars=4))


def test_streaming_line_decoder_rejects_overlong_line_across_chunks() -> None:
    with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
        list(iter_lines(iter(("al", "pha")), max_line_chars=4))


def test_streaming_line_decoder_allows_exact_max_line_chars_across_chunks() -> None:
    assert list(iter_lines(iter(("al", "pha")), max_line_chars=5)) == ["alpha"]


@pytest.mark.parametrize(
    ("text_chunks", "expected_lines"),
    [
        pytest.param(
            ("firs", "t\nnext"),
            ["first", "next"],
            id="lf-delimiter",
        ),
        pytest.param(
            ("firs", "t\r", "\nnext"),
            ["first", "next"],
            id="split-crlf-delimiter",
        ),
    ],
)
def test_streaming_line_decoder_allows_exact_max_line_chars_before_delimiter(
    text_chunks: tuple[str, ...],
    expected_lines: list[str],
) -> None:
    assert list(iter_lines(iter(text_chunks), max_line_chars=5)) == expected_lines


@pytest.mark.parametrize(
    "text_chunks",
    [
        pytest.param(("first\n",), id="lf-delimiter"),
        pytest.param(("firs", "t\r\n"), id="split-crlf-delimiter"),
    ],
)
def test_streaming_line_decoder_rejects_overlong_line_before_delimiter(
    text_chunks: tuple[str, ...],
) -> None:
    with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
        list(iter_lines(iter(text_chunks), max_line_chars=4))


def test_streaming_line_decoder_handles_many_small_chunks_as_one_pending_line() -> None:
    assert list(iter_lines(iter(("x",) * 128), max_line_chars=128)) == ["x" * 128]


def test_streaming_line_decoder_handles_split_carriage_return_line_endings() -> None:
    text_chunks = iter(("alpha\r", "\nbeta\r", "gamma"))

    assert list(iter_lines(text_chunks)) == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize(
    ("text_chunks", "expected_lines"),
    [
        pytest.param(
            ("alpha\nbeta\r\ngamma\rdone",),
            ["alpha", "beta", "gamma", "done"],
            id="mixed-line-endings-one-chunk",
        ),
        pytest.param(
            ("alpha\r", "", "\nbeta"),
            ["alpha", "beta"],
            id="deferred-cr-through-empty-chunk",
        ),
        pytest.param(
            ("\r", "\n", "\r", "tail"),
            ["", "", "tail"],
            id="empty-lines-across-split-crlf",
        ),
    ],
)
def test_streaming_line_decoder_handles_line_ending_matrix(
    text_chunks: tuple[str, ...],
    expected_lines: list[str],
) -> None:
    assert list(iter_lines(iter(text_chunks))) == expected_lines


async def test_async_streaming_line_decoder_matches_sync_line_endings() -> None:
    async def text_source() -> AsyncIterator[str]:
        for chunk in ("alpha\r", "", "\nbeta\n"):
            yield chunk

    assert [line async for line in aiter_lines(text_source())] == ["alpha", "beta"]


def test_text_decoder_closes_sync_source_when_decoder_setup_fails() -> None:
    byte_chunks = ClosableByteIterator((b"alpha",))
    text_chunks = iter_text_chunks(byte_chunks, encoding="foghttp-unknown-codec", errors="replace")

    with pytest.raises(LookupError):
        next(text_chunks)

    assert byte_chunks.closed


async def test_text_decoder_closes_async_source_when_decoder_setup_fails() -> None:
    byte_chunks = AsyncClosableByteIterator((b"alpha",))
    text_chunks = aiter_text_chunks(byte_chunks, encoding="foghttp-unknown-codec", errors="replace")

    with pytest.raises(LookupError):
        await anext(text_chunks)

    assert byte_chunks.closed
