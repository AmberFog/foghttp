__all__ = (
    "compressed_body",
    "gzip_body",
    "raw_deflate_body",
    "zlib_deflate_body",
)

import gzip
import zlib

from .constants import (
    BROTLI_COMPRESSED_BODY,
    BROTLI_ENCODING_PATH,
    DECOMPRESSED_BODY,
    GZIP_ENCODING_PATH,
    RAW_DEFLATE_ENCODING_PATH,
    ZLIB_DEFLATE_ENCODING_PATH,
)


def compressed_body(path: str, body: bytes = DECOMPRESSED_BODY) -> bytes:
    match path:
        case path if path == GZIP_ENCODING_PATH:
            return gzip_body(body)
        case path if path == ZLIB_DEFLATE_ENCODING_PATH:
            return zlib_deflate_body(body)
        case path if path == RAW_DEFLATE_ENCODING_PATH:
            return raw_deflate_body(body)
        case path if path == BROTLI_ENCODING_PATH:
            return BROTLI_COMPRESSED_BODY
        case _unknown:
            msg = f"unsupported compressed response path: {path}"
            raise ValueError(msg)


def gzip_body(body: bytes) -> bytes:
    return gzip.compress(body)


def zlib_deflate_body(body: bytes) -> bytes:
    return zlib.compress(body)


def raw_deflate_body(body: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(body) + compressor.flush()
