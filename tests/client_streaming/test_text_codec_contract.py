import pytest

from foghttp._streaming.text.async_chunks import aiter_text_chunks
from foghttp._streaming.text.sync_chunks import iter_text_chunks
from tests.client_streaming.text_decoding_sources import (
    AsyncClosableByteIterator,
    ClosableByteIterator,
)


@pytest.mark.parametrize(
    ("encoding", "byte_chunks", "expected_text"),
    [
        pytest.param("cp1251", (b"\xcf\xf0", b"\xe8\xe2\xe5\xf2"), "Привет", id="text-codec-alias"),
        pytest.param("utf-16", (b"\xff", b"\xfeA", b"\x00B\x00"), "AB", id="split-utf16-bom"),
    ],
)
def test_sync_text_codecs_preserve_split_characters(
    encoding: str,
    byte_chunks: tuple[bytes, ...],
    expected_text: str,
) -> None:
    source = ClosableByteIterator(byte_chunks)

    chunks = list(iter_text_chunks(source, encoding=encoding, errors="strict"))

    assert all(isinstance(chunk, str) for chunk in chunks)
    assert "".join(chunks) == expected_text
    assert source.closed


@pytest.mark.parametrize(
    ("encoding", "byte_chunks", "expected_text"),
    [
        pytest.param("cp1251", (b"\xcf\xf0", b"\xe8\xe2\xe5\xf2"), "Привет", id="text-codec-alias"),
        pytest.param("utf-16", (b"\xff", b"\xfeA", b"\x00B\x00"), "AB", id="split-utf16-bom"),
    ],
)
async def test_async_text_codecs_preserve_split_characters(
    encoding: str,
    byte_chunks: tuple[bytes, ...],
    expected_text: str,
) -> None:
    source = AsyncClosableByteIterator(byte_chunks)

    chunks = [chunk async for chunk in aiter_text_chunks(source, encoding=encoding, errors="strict")]

    assert all(isinstance(chunk, str) for chunk in chunks)
    assert "".join(chunks) == expected_text
    assert source.closed


def test_sync_text_decoder_replaces_invalid_bytes() -> None:
    source = ClosableByteIterator((b"alpha\xff", b"\xc3", b"("))

    assert "".join(iter_text_chunks(source, encoding="utf-8", errors="replace")) == "alpha\ufffd\ufffd("
    assert source.closed


async def test_async_text_decoder_replaces_invalid_bytes() -> None:
    source = AsyncClosableByteIterator((b"alpha\xff", b"\xc3", b"("))

    assert "".join([chunk async for chunk in aiter_text_chunks(source, encoding="utf-8", errors="replace")]) == (
        "alpha\ufffd\ufffd("
    )
    assert source.closed


def test_sync_text_decoder_preserves_strict_errors() -> None:
    source = ClosableByteIterator((b"\xff",))

    with pytest.raises(UnicodeDecodeError):
        next(iter_text_chunks(source, encoding="utf-8", errors="strict"))

    assert source.closed


async def test_async_text_decoder_preserves_strict_errors() -> None:
    source = AsyncClosableByteIterator((b"\xff",))

    with pytest.raises(UnicodeDecodeError):
        await anext(aiter_text_chunks(source, encoding="utf-8", errors="strict"))

    assert source.closed
