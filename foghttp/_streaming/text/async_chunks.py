__all__ = ("aiter_text_chunks",)

import codecs
from collections.abc import AsyncIterator, Callable

from ..._response.encoding import validate_text_encoding
from .iterators import close_async_iterator


async def aiter_text_chunks(
    byte_chunks: AsyncIterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    try:
        validate_text_encoding(encoding)
        decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
        async for chunk in byte_chunks:
            if text := decoder.decode(chunk):
                yield text
        if text := decoder.decode(b"", final=True):
            yield text
    finally:
        if close is not None:
            close()
        await close_async_iterator(byte_chunks)
