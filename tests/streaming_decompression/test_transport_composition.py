from urllib.parse import urlencode

import foghttp
from tests.client_retry.constants import EXPECTED_ATTEMPTS, STATUS_THEN_OK_PATH
from tests.client_retry.server import start_retry_test_server

from .constants import DECODED_BODY
from .payloads import EncodedResponse, gzip_bytes
from .server import ServerFactory


def test_sync_explicit_http_proxy_decodes_content(
    decompression_server: ServerFactory,
    unused_tcp_port: int,
) -> None:
    proxy = decompression_server(EncodedResponse(gzip_bytes(DECODED_BODY)))
    target = f"http://127.0.0.1:{unused_tcp_port}/via-proxy"
    with (
        foghttp.Client(proxy=proxy.url, trust_env=False) as client,
        client.stream("GET", target, decode_content=True) as response,
    ):
        assert b"".join(response.iter_bytes()) == DECODED_BODY
        assert "content-encoding" not in response.headers
        assert client.stats().stream_decoder_reserved_bytes == 0
    assert proxy.requests[0].request_line == f"GET {target} HTTP/1.1"
    assert "accept-encoding" not in proxy.requests[0].headers


async def test_async_explicit_http_proxy_decodes_content(
    decompression_server: ServerFactory,
    unused_tcp_port: int,
) -> None:
    proxy = decompression_server(EncodedResponse(gzip_bytes(DECODED_BODY)))
    target = f"http://127.0.0.1:{unused_tcp_port}/via-proxy"
    async with (
        foghttp.AsyncClient(proxy=proxy.url, trust_env=False) as client,
        client.stream("GET", target, decode_content=True) as response,
    ):
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == DECODED_BODY
        assert "content-encoding" not in response.headers
        assert client.stats().stream_decoder_reserved_bytes == 0
    assert proxy.requests[0].request_line == f"GET {target} HTTP/1.1"
    assert "accept-encoding" not in proxy.requests[0].headers


def test_sync_redirect_final_response_keeps_decoding_mode(
    decompression_server: ServerFactory,
    sync_http_server: str,
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(DECODED_BODY)))
    query = urlencode({"status": 302, "location": server.url})
    with (
        foghttp.Client(trust_env=False, follow_redirects=True) as client,
        client.stream("GET", f"{sync_http_server}/redirect-to-location?{query}", decode_content=True) as response,
    ):
        assert b"".join(response.iter_bytes()) == DECODED_BODY
        assert "content-encoding" not in response.headers
        assert client.stats().stream_decoder_reserved_bytes == 0
    assert server.state.snapshot().request_count == 1


async def test_async_redirect_final_response_keeps_decoding_mode(
    decompression_server: ServerFactory,
    http_server: str,
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(DECODED_BODY)))
    query = urlencode({"status": 302, "location": server.url})
    async with (
        foghttp.AsyncClient(trust_env=False, follow_redirects=True) as client,
        client.stream("GET", f"{http_server}/redirect-to-location?{query}", decode_content=True) as response,
    ):
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == DECODED_BODY
        assert "content-encoding" not in response.headers
        assert client.stats().stream_decoder_reserved_bytes == 0
    assert server.state.snapshot().request_count == 1


def test_sync_retry_decodes_only_final_response() -> None:
    with (
        start_retry_test_server() as server,
        foghttp.Client(
            trust_env=False,
            retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
            limits=foghttp.Limits(max_stream_decoded_bytes=len(b"ok")),
        ) as client,
        client.stream("GET", server.url + STATUS_THEN_OK_PATH, decode_content=True) as response,
    ):
        assert b"".join(response.iter_bytes()) == b"ok"
        assert client.stats().stream_decoder_reserved_bytes == 0
    requests = server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id == requests[1].connection_id


async def test_async_retry_decodes_only_final_response() -> None:
    with start_retry_test_server() as server:
        async with (
            foghttp.AsyncClient(
                trust_env=False,
                retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
                limits=foghttp.Limits(max_stream_decoded_bytes=len(b"ok")),
            ) as client,
            client.stream("GET", server.url + STATUS_THEN_OK_PATH, decode_content=True) as response,
        ):
            assert b"".join([chunk async for chunk in response.aiter_bytes()]) == b"ok"
            assert client.stats().stream_decoder_reserved_bytes == 0
    requests = server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id == requests[1].connection_id
