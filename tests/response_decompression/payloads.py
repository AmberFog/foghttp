__all__ = (
    "compressed_body",
    "gzip_body",
    "multiple_encoding_fields_body",
    "raw_deflate_body",
    "stored_multiblock_raw_deflate_body",
    "zlib_deflate_body",
    "zlib_raw_polyglot_body",
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
    if path == GZIP_ENCODING_PATH:
        return gzip_body(body)
    if path == ZLIB_DEFLATE_ENCODING_PATH:
        return zlib_deflate_body(body)
    if path == RAW_DEFLATE_ENCODING_PATH:
        return raw_deflate_body(body)
    if path == BROTLI_ENCODING_PATH:
        return BROTLI_COMPRESSED_BODY

    msg = f"unsupported compressed response path: {path}"
    raise ValueError(msg)


def gzip_body(body: bytes) -> bytes:
    return gzip.compress(body)


def multiple_encoding_fields_body(body: bytes = DECOMPRESSED_BODY) -> bytes:
    return zlib_deflate_body(gzip_body(body))


def zlib_deflate_body(body: bytes) -> bytes:
    return zlib.compress(body)


def raw_deflate_body(body: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(body) + compressor.flush()


def stored_multiblock_raw_deflate_body(body: bytes) -> bytes:
    # A nonfinal stored block starts with 0x00, so this raw control has no zlib CMF/FLG.
    compressor = zlib.compressobj(level=0, wbits=-zlib.MAX_WBITS)
    midpoint = len(body) // 2
    prefix = compressor.compress(body[:midpoint]) + compressor.flush(zlib.Z_SYNC_FLUSH)
    return prefix + compressor.compress(body[midpoint:]) + compressor.flush()


def zlib_raw_polyglot_body() -> tuple[bytes, bytes]:
    # RFC 1950 section 2.2 makes 0x7801 a valid CMF/FLG header. Under RFC 1951
    # section 3.2.4 these first 16 bytes also form a complete raw stream for b"\x01".
    # The buffered contract commits to zlib after its header, so that alternate
    # raw interpretation must not hide a missing or invalid zlib checksum.
    # https://www.rfc-editor.org/rfc/rfc1950.html#section-2.2
    # https://www.rfc-editor.org/rfc/rfc1951.html#section-3.2.4
    prefix = bytes.fromhex("78 01 00 fe ff 01 00 00 00 ff ff 01 00 00 ff ff")
    stored_size = 65534
    stored_prefix = prefix[7:]
    remainder = b"x" * (stored_size - len(stored_prefix))
    decoded = stored_prefix + remainder
    final_empty_block = b"\x01\x00\x00\xff\xff"
    checksum = zlib.adler32(decoded).to_bytes(4, "big")
    return prefix + remainder + final_empty_block + checksum, decoded
