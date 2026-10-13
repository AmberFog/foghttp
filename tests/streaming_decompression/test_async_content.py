import pytest

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats

from .cases import SUPPORTED_BODIES, TRUNCATED_BODIES, DecodeOptions
from .constants import DECODED_BODY, TEXT_BODY
from .payloads import EncodedResponse, gzip_bytes
from .server import ServerFactory


@pytest.mark.parametrize(("case", "expected"), SUPPORTED_BODIES)
async def test_async_decodes_supported_content(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    expected: bytes,
) -> None:
    server = decompression_server(case)
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            assert "content-encoding" not in response.headers
            assert "content-length" not in response.headers
            assert response.headers["etag"] == '"encoded-validator"'
            assert b"".join([chunk async for chunk in response.aiter_bytes()]) == expected
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="decoded EOF must release its reservation and request permit",
        )
    assert "accept-encoding" not in server.requests[0].headers


@pytest.mark.parametrize("decode_options", [{}, {"decode_content": False}], ids=["default", "explicit-raw"])
@pytest.mark.parametrize("encoding", ["gzip", "zstd"])
async def test_async_raw_mode_preserves_wire_bytes_and_headers(
    decompression_server: ServerFactory,
    decode_options: DecodeOptions,
    encoding: str,
) -> None:
    encoded = gzip_bytes(DECODED_BODY)
    server = decompression_server(EncodedResponse(encoded, (encoding,)))
    limits = foghttp.Limits(max_stream_decoded_bytes=0, max_stream_decoder_memory_bytes=0)
    async with (
        foghttp.AsyncClient(limits=limits, trust_env=False) as client,
        client.stream("GET", server.url, **decode_options) as response,
    ):
        assert response.headers["content-encoding"] == encoding
        assert response.headers["content-length"] == str(len(encoded))
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == encoded
        assert client.stats().stream_decoder_reserved_bytes == 0


async def test_async_text_and_lines_use_decoded_bytes(decompression_server: ServerFactory) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(TEXT_BODY.encode())))
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            assert "".join([chunk async for chunk in response.aiter_text()]) == TEXT_BODY
            with pytest.raises(foghttp.LifecycleError):
                response.aiter_bytes()
        async with client.stream("GET", server.url, decode_content=True) as response:
            assert [line async for line in response.aiter_lines()] == TEXT_BODY.splitlines()


@pytest.mark.parametrize("case", TRUNCATED_BODIES)
async def test_async_invalid_body_fails_during_iteration(
    decompression_server: ServerFactory,
    case: EncodedResponse,
) -> None:
    server = decompression_server(case)
    async with foghttp.AsyncClient(trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            with pytest.raises(foghttp.ResponseDecodingError):
                _ = [chunk async for chunk in response.aiter_bytes()]
            await response.aclose()
            await response.aclose()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="content failure must release its reservation and request permit",
        )
        assert (await client.get(f"{server.url}/healthy")).content == b"healthy"
