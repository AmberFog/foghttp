import pytest

import foghttp
from foghttp._streaming.text import aiter_text_chunks, iter_lines, iter_text_chunks
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
