__all__ = ("iter_text_chunks",)

import codecs
from collections.abc import Iterator

from ..._response.encoding import validate_text_encoding
from .iterators import CloseStream, close_iterator, closing_stream


def iter_text_chunks(
    byte_chunks: Iterator[bytes],
    *,
    encoding: str,
    errors: str,
    close: CloseStream | None = None,
) -> Iterator[str]:
    try:
        with closing_stream(close):
            validate_text_encoding(encoding)
            decoder = codecs.getincrementaldecoder(encoding)(errors=errors)
            for chunk in byte_chunks:
                if text := decoder.decode(chunk):
                    yield text
            if text := decoder.decode(b"", final=True):
                yield text
    finally:
        close_iterator(byte_chunks)
