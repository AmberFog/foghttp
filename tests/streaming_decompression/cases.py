__all__ = ("GATED_BODIES", "INVALID_PLANS", "SUPPORTED_BODIES", "TRUNCATED_BODIES", "DecodeOptions")

from typing import TypedDict
import zlib

import pytest

from tests.response_decompression.constants import BROTLI_COMPRESSED_BODY, DECOMPRESSED_BODY
from tests.response_decompression.payloads import raw_deflate_body

from .constants import DECODED_BODY, FIRST_OUTPUT, GZIP_RESERVATION, TAIL_OUTPUT
from .payloads import EncodedResponse, gated_gzip, gzip_bytes, nested_gzip


class DecodeOptions(TypedDict, total=False):
    decode_content: bool


GATED_BODIES = (
    pytest.param(gated_gzip(), FIRST_OUTPUT, TAIL_OUTPUT, GZIP_RESERVATION, id="gzip"),
    pytest.param(
        # Brotli quality=4/lgwin=22: flush 196625 Z bytes, then finish in the last byte.
        EncodedResponse(
            bytes.fromhex("2b08800140422b1e0b44f95ec00003"),  # pragma: allowlist secret
            ("br",),
            gate_after=13,
        ),
        b"Z" * (3 * 64 * 1024 + 17),
        b"",
        32 * 1024 * 1024 + 3 * 64 * 1024,
        id="brotli-pending-output",
    ),
)
SUPPORTED_BODIES = (
    pytest.param(EncodedResponse(gzip_bytes(DECODED_BODY)), DECODED_BODY, id="gzip"),
    pytest.param(EncodedResponse(zlib.compress(DECODED_BODY), ("deflate",)), DECODED_BODY, id="zlib"),
    pytest.param(EncodedResponse(BROTLI_COMPRESSED_BODY, ("br",)), DECOMPRESSED_BODY, id="brotli"),
    pytest.param(
        EncodedResponse(gzip_bytes(b"") + gzip_bytes(DECODED_BODY) + gzip_bytes(b""), ("X-GzIp",)),
        DECODED_BODY,
        id="gzip-members-and-alias",
    ),
    pytest.param(
        EncodedResponse(zlib.compress(gzip_bytes(DECODED_BODY)), (" , identity, GZip", "Deflate, ")),
        DECODED_BODY,
        id="multiple-fields-reverse-order",
    ),
    pytest.param(
        EncodedResponse(nested_gzip(DECODED_BODY, 4), ("gzip,gzip,gzip,gzip",)),
        DECODED_BODY,
        id="four-layers",
    ),
)
INVALID_PLANS = (
    pytest.param(("zstd",), id="unknown"),
    pytest.param(("gzip,zstd",), id="mixed-unknown"),
    pytest.param(("gzip;level=1",), id="parameters"),
    pytest.param(("g zip",), id="malformed-token"),
    pytest.param(("gzip,gzip,gzip,gzip,gzip",), id="five-layers"),
)
TRUNCATED_BODIES = (
    pytest.param(EncodedResponse(b""), id="zero-encoded-gzip"),
    pytest.param(EncodedResponse(b"", ("deflate",)), id="zero-encoded-deflate"),
    pytest.param(EncodedResponse(b"", ("br",)), id="zero-encoded-brotli"),
    pytest.param(EncodedResponse(gzip_bytes(DECODED_BODY)[:-1]), id="gzip-truncated-trailer"),
    pytest.param(EncodedResponse(zlib.compress(DECODED_BODY)[:-1], ("deflate",)), id="zlib-truncated"),
    pytest.param(EncodedResponse(BROTLI_COMPRESSED_BODY[:-1], ("br",)), id="brotli-truncated"),
    pytest.param(EncodedResponse(raw_deflate_body(DECODED_BODY), ("deflate",)), id="raw-deflate"),
)
