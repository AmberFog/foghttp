__all__ = ("aiter_text_chunks",)

import codecs
from collections.abc import AsyncIterator

from ..._response.encoding import validate_text_encoding
from .iterators import CloseStream, close_async_iterator, closing_stream


async def aiter_text_chunks(
    byte_chunks: AsyncIterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: CloseStream | None = None,
) -> AsyncIterator[str]:
    try:
        with closing_stream(close):
            validate_text_encoding(encoding)
            decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
            async for chunk in byte_chunks:
                if text := decoder.decode(chunk):
                    yield text
            if text := decoder.decode(b"", final=True):
                yield text
    finally:
        await close_async_iterator(byte_chunks)
