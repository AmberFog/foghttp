__all__ = ("iter_text_chunks",)

import codecs
from collections.abc import Callable, Iterator

from ..._response.encoding import validate_text_encoding
from .iterators import close_iterator


def iter_text_chunks(
    byte_chunks: Iterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: Callable[[], None] | None = None,
) -> Iterator[str]:
    try:
        validate_text_encoding(encoding)
        decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
        for chunk in byte_chunks:
            if text := decoder.decode(chunk):
                yield text
        if text := decoder.decode(b"", final=True):
            yield text
    finally:
        if close is not None:
            close()
        close_iterator(byte_chunks)
