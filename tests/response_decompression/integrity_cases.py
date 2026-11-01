__all__ = ("INVALID_DEFLATE_BODIES", "VALID_BUFFERED_BODIES", "integrity_limits")

import pytest

from foghttp import Limits
from tests.streaming_decompression.payloads import EncodedResponse

from .constants import BROTLI_COMPRESSED_BODY, DECOMPRESSED_BODY
from .payloads import (
    gzip_body,
    raw_deflate_body,
    stored_multiblock_raw_deflate_body,
    zlib_deflate_body,
    zlib_raw_polyglot_body,
)


INTEGRITY_BODY = b"a" * (1024 * 1024)
ZLIB_BODY = zlib_deflate_body(INTEGRITY_BODY)
RAW_BODY = raw_deflate_body(INTEGRITY_BODY)
POLYGLOT_ZLIB_BODY, POLYGLOT_DECODED_BODY = zlib_raw_polyglot_body()
INVALID_DEFLATE_BODIES = (
    pytest.param(ZLIB_BODY[: len(ZLIB_BODY) // 2], id="zlib-half"),
    pytest.param(ZLIB_BODY[:-1], id="zlib-missing-last-byte"),
    pytest.param(ZLIB_BODY[:-4], id="zlib-missing-adler32"),
    pytest.param(ZLIB_BODY[:-1] + bytes([ZLIB_BODY[-1] ^ 1]), id="zlib-invalid-adler32"),
    pytest.param(RAW_BODY[: len(RAW_BODY) // 2], id="raw-half"),
    pytest.param(RAW_BODY[:-1], id="raw-missing-last-byte"),
    pytest.param(POLYGLOT_ZLIB_BODY[:16], id="zlib-polyglot-truncated-prefix"),
    pytest.param(POLYGLOT_ZLIB_BODY[:-4], id="zlib-polyglot-missing-adler32"),
    pytest.param(
        POLYGLOT_ZLIB_BODY[:-1] + bytes([POLYGLOT_ZLIB_BODY[-1] ^ 1]),
        id="zlib-polyglot-invalid-adler32",
    ),
)
VALID_BUFFERED_BODIES = (
    pytest.param(EncodedResponse(ZLIB_BODY, ("deflate",)), INTEGRITY_BODY, id="zlib-nonempty"),
    pytest.param(EncodedResponse(zlib_deflate_body(b""), ("deflate",)), b"", id="zlib-empty"),
    pytest.param(EncodedResponse(RAW_BODY, ("deflate",)), INTEGRITY_BODY, id="raw-nonempty"),
    pytest.param(EncodedResponse(raw_deflate_body(b""), ("deflate",)), b"", id="raw-empty"),
    pytest.param(
        EncodedResponse(POLYGLOT_ZLIB_BODY, ("deflate",)),
        POLYGLOT_DECODED_BODY,
        id="zlib-polyglot-complete",
    ),
    pytest.param(
        EncodedResponse(stored_multiblock_raw_deflate_body(DECOMPRESSED_BODY), ("deflate",)),
        DECOMPRESSED_BODY,
        id="raw-stored-multiple-blocks",
    ),
    pytest.param(
        EncodedResponse(gzip_body(b"") + gzip_body(DECOMPRESSED_BODY) + gzip_body(b"")),
        DECOMPRESSED_BODY,
        id="gzip-multiple-members",
    ),
    pytest.param(EncodedResponse(BROTLI_COMPRESSED_BODY, ("br",)), DECOMPRESSED_BODY, id="brotli"),
)


def integrity_limits() -> Limits:
    return Limits(
        max_active_requests=1,
        max_pending_requests=0,
        max_response_body_size=len(INTEGRITY_BODY),
        max_buffered_response_bytes=2 * len(INTEGRITY_BODY),
        max_idle_connections_per_host=1,
    )
