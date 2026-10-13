import pytest

import foghttp
from tests.support.transport_stats import wait_for_sync_transport_stats

from .cases import SUPPORTED_BODIES, TRUNCATED_BODIES, DecodeOptions
from .constants import DECODED_BODY, TEXT_BODY
from .payloads import EncodedResponse, gzip_bytes
from .server import ServerFactory


@pytest.mark.parametrize(("case", "expected"), SUPPORTED_BODIES)
def test_sync_decodes_supported_content(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    expected: bytes,
) -> None:
    server = decompression_server(case)
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            assert "content-encoding" not in response.headers
            assert "content-length" not in response.headers
            assert response.headers["etag"] == '"encoded-validator"'
            assert b"".join(response.iter_bytes()) == expected
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="decoded EOF must release its reservation and request permit",
        )
    assert "accept-encoding" not in server.requests[0].headers


@pytest.mark.parametrize("decode_options", [{}, {"decode_content": False}], ids=["default", "explicit-raw"])
@pytest.mark.parametrize("encoding", ["gzip", "zstd"])
def test_sync_raw_mode_preserves_wire_bytes_and_headers(
    decompression_server: ServerFactory,
    decode_options: DecodeOptions,
    encoding: str,
) -> None:
    encoded = gzip_bytes(DECODED_BODY)
    server = decompression_server(EncodedResponse(encoded, (encoding,)))
    limits = foghttp.Limits(max_stream_decoded_bytes=0, max_stream_decoder_memory_bytes=0)
    with (
        foghttp.Client(limits=limits, trust_env=False) as client,
        client.stream("GET", server.url, **decode_options) as response,
    ):
        assert response.headers["content-encoding"] == encoding
        assert response.headers["content-length"] == str(len(encoded))
        assert b"".join(response.iter_bytes()) == encoded
        assert client.stats().stream_decoder_reserved_bytes == 0


def test_sync_text_and_lines_use_decoded_bytes(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(TEXT_BODY.encode())))
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            assert "".join(response.iter_text()) == TEXT_BODY
            with pytest.raises(foghttp.LifecycleError):
                response.iter_bytes()
        with client.stream("GET", server.url, decode_content=True) as response:
            assert list(response.iter_lines()) == TEXT_BODY.splitlines()


@pytest.mark.parametrize("case", TRUNCATED_BODIES)
def test_sync_invalid_body_fails_during_iteration(
    decompression_server: ServerFactory,
    case: EncodedResponse,
) -> None:
    server = decompression_server(case)
    with foghttp.Client(trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            with pytest.raises(foghttp.ResponseDecodingError):
                list(response.iter_bytes())
            response.close()
            response.close()
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="content failure must release its reservation and request permit",
        )
        assert client.get(f"{server.url}/healthy").content == b"healthy"
