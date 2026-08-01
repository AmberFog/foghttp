from collections.abc import AsyncIterator, Iterator
from typing import assert_type

import foghttp
from foghttp.types import (
    AsyncStreamResponseProtocol,
    BufferedResponseProtocol,
    RequestProtocol,
    ResponseProtocol,
    StreamResponseProtocol,
)


def response_status(response: ResponseProtocol) -> tuple[int, str]:
    return response.status_code, response.request.method


def sync_stream_contract(response: foghttp.StreamResponse) -> StreamResponseProtocol:
    stream: StreamResponseProtocol = response
    assert_type(stream.iter_bytes(), Iterator[bytes])
    return stream


def async_stream_contract(response: foghttp.AsyncStreamResponse) -> AsyncStreamResponseProtocol:
    stream: AsyncStreamResponseProtocol = response
    assert_type(stream.aiter_bytes(), AsyncIterator[bytes])
    return stream


def test_prepared_and_completed_requests_share_public_metadata_contract() -> None:
    prepared = foghttp.Request(
        "GET",
        "https://example.invalid/items",
        extensions={"tests.request_id": "request-1"},
    )
    completed = foghttp.RequestInfo(
        method=prepared.method,
        url=prepared.url,
        headers=prepared.headers,
        extensions=prepared.extensions,
    )

    prepared_contract: RequestProtocol = prepared
    completed_contract: RequestProtocol = completed

    assert prepared_contract.method == completed_contract.method
    assert prepared_contract.url == completed_contract.url
    assert prepared_contract.extensions is completed_contract.extensions


def test_buffered_response_satisfies_public_response_protocols() -> None:
    request = foghttp.RequestInfo(
        method="GET",
        url="https://example.invalid/items",
        headers=foghttp.Headers(),
    )
    response = foghttp.Response(
        status_code=200,
        headers=foghttp.Headers({"Content-Type": "application/json"}),
        content=b'{"ok":true}',
        url=request.url,
        request=request,
        http_version="HTTP/1.1",
        elapsed=0.01,
    )

    response_contract: ResponseProtocol = response
    buffered_contract: BufferedResponseProtocol = response

    assert response_status(response_contract) == (200, "GET")
    assert buffered_contract.json() == {"ok": True}
    assert_type(buffered_contract.content, bytes)
