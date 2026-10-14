__all__ = ("ADVERTISED_CODECS", "ADVERTISEMENT", "EXPLICIT_HEADERS", "NegotiationOptions")

from typing import TypedDict

import pytest

from tests.response_decompression.constants import (
    BROTLI_ENCODING_PATH,
    GZIP_ENCODING_PATH,
    ZLIB_DEFLATE_ENCODING_PATH,
)
from tests.response_decompression.payloads import compressed_body
from tests.streaming_decompression.payloads import EncodedResponse


class NegotiationOptions(TypedDict, total=False):
    auto_accept_encoding: bool | None


ADVERTISEMENT = "gzip, deflate, br"
ADVERTISED_CODECS = (
    pytest.param(EncodedResponse(compressed_body(GZIP_ENCODING_PATH)), id="gzip"),
    pytest.param(EncodedResponse(compressed_body(ZLIB_DEFLATE_ENCODING_PATH), ("deflate",)), id="deflate"),
    pytest.param(EncodedResponse(compressed_body(BROTLI_ENCODING_PATH), ("br",)), id="brotli"),
)
EXPLICIT_HEADERS = (
    pytest.param([("Accept-Encoding", "")], [""], id="empty"),
    pytest.param([("aCcEpT-eNcOdInG", "identity")], ["identity"], id="mixed-case-identity"),
    pytest.param([("accept-encoding", "gzip;q=0, br;q=0.5, *;q=0")], ["gzip;q=0, br;q=0.5, *;q=0"], id="weights"),
    pytest.param([("ACCEPT-ENCODING", "gzip;q=0")], ["gzip;q=0"], id="zero-quality"),
    pytest.param(
        [("Accept-Encoding", "deflate;q=0.3"), ("aCcEpT-eNcOdInG", "br;q=1")],
        ["deflate;q=0.3", "br;q=1"],
        id="repeated-case-variants",
    ),
)
