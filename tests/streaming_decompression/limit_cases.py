__all__ = ("CAPPED_FAILURES", "CAPPED_SUCCESSES")

import zlib

import pytest

from .constants import DECODED_BODY
from .payloads import EncodedResponse, gzip_bytes


CAPPED_SUCCESSES = (
    pytest.param(EncodedResponse(gzip_bytes(DECODED_BODY)), len(DECODED_BODY), DECODED_BODY, id="gzip-exact"),
    pytest.param(EncodedResponse(DECODED_BODY, ()), len(DECODED_BODY), DECODED_BODY, id="identity-exact"),
    pytest.param(EncodedResponse(gzip_bytes(DECODED_BODY)), None, DECODED_BODY, id="unlimited"),
    pytest.param(EncodedResponse(gzip_bytes(b"")), 0, b"", id="gzip-empty"),
    pytest.param(EncodedResponse(zlib.compress(b""), ("deflate",)), 0, b"", id="zlib-empty"),
    pytest.param(EncodedResponse(b"\x3b", ("br",)), 0, b"", id="brotli-empty"),
    pytest.param(EncodedResponse(b"", ()), 0, b"", id="identity-empty"),
)
CAPPED_FAILURES = (
    pytest.param(EncodedResponse(gzip_bytes(DECODED_BODY)), len(DECODED_BODY) - 1, id="gzip-cap-plus-one"),
    pytest.param(EncodedResponse(DECODED_BODY, ()), len(DECODED_BODY) - 1, id="identity-cap-plus-one"),
    pytest.param(EncodedResponse(gzip_bytes(b"x")), 0, id="gzip-zero"),
    pytest.param(EncodedResponse(b"x", ()), 0, id="identity-zero"),
    # The final output fits, but the inner gzip representation does not.
    pytest.param(EncodedResponse(zlib.compress(gzip_bytes(b"x")), ("gzip,deflate",)), 1, id="intermediate-cap"),
)
