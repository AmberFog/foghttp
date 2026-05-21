import pytest

import foghttp
from foghttp.status_codes.success import OK, RESET_CONTENT

from .constants import (
    BODY_CONTENT_TYPE,
    DECODED_BODY_LIMIT,
    DECODED_TOO_LARGE_BODY,
    DECODED_TOO_LARGE_PATH,
    DECOMPRESSED_BODY,
    GZIP_ENCODING_PATH,
    INVALID_GZIP_PATH,
    RESET_CONTENT_PATH,
    SUPPORTED_ENCODING_CASES,
    UNSUPPORTED_ENCODED_BODY,
    UNSUPPORTED_ENCODING,
    UNSUPPORTED_ENCODING_PATH,
)
from .helpers import budget_below_decoding_transient_size
from .payloads import compressed_body
from .server import ResponseDecompressionServer


@pytest.mark.parametrize(
    "path",
    tuple(pytest.param(path, id=case_id) for path, case_id in SUPPORTED_ENCODING_CASES),
)
async def test_async_buffered_response_decodes_supported_content_encoding(
    response_decompression_server: ResponseDecompressionServer,
    path: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(f"{response_decompression_server.url}{path}")
        stats = client.stats()

    assert response.status_code == OK
    assert response.content == DECOMPRESSED_BODY
    assert response.headers["content-type"] == BODY_CONTENT_TYPE
    assert "content-encoding" not in response.headers
    assert "content-length" not in response.headers
    assert stats.total_requests == 1
    assert stats.failed_requests == 0
    assert stats.buffered_response_bytes == 0


async def test_async_buffered_response_leaves_unsupported_content_encoding_encoded(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(
            f"{response_decompression_server.url}{UNSUPPORTED_ENCODING_PATH}",
        )

    assert response.status_code == OK
    assert response.content == UNSUPPORTED_ENCODED_BODY
    assert response.headers["content-encoding"] == UNSUPPORTED_ENCODING
    assert response.headers["content-length"] == str(len(UNSUPPORTED_ENCODED_BODY))


async def test_async_head_response_preserves_encoded_body_metadata(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    encoded_body = compressed_body(GZIP_ENCODING_PATH)

    async with foghttp.AsyncClient() as client:
        response = await client.head(f"{response_decompression_server.url}{GZIP_ENCODING_PATH}")
        stats = client.stats()

    assert response.status_code == OK
    assert response.content == b""
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-length"] == str(len(encoded_body))
    assert stats.total_requests == 1
    assert stats.failed_requests == 0


async def test_async_reset_content_response_preserves_encoded_body_metadata(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(f"{response_decompression_server.url}{RESET_CONTENT_PATH}")
        stats = client.stats()

    assert response.status_code == RESET_CONTENT
    assert response.content == b""
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-length"] == "0"
    assert stats.total_requests == 1
    assert stats.failed_requests == 0


async def test_async_buffered_response_rejects_invalid_encoded_body(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(foghttp.RequestError, match="failed to decode gzip response body"):
            await client.get(f"{response_decompression_server.url}{INVALID_GZIP_PATH}")

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.buffered_response_bytes == 0


async def test_async_buffered_response_limit_applies_to_decoded_body(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    limits = foghttp.Limits(max_response_body_size=DECODED_BODY_LIMIT)

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            await client.get(f"{response_decompression_server.url}{DECODED_TOO_LARGE_PATH}")

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.buffered_response_bytes == 0


async def test_async_buffered_response_budget_applies_while_decoding(
    response_decompression_server: ResponseDecompressionServer,
) -> None:
    limits = foghttp.Limits(
        max_response_body_size=len(DECODED_TOO_LARGE_BODY),
        max_buffered_response_bytes=budget_below_decoding_transient_size(),
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyBudgetExceededError,
            match="buffered response bodies exceeded max_buffered_response_bytes",
        ):
            await client.get(f"{response_decompression_server.url}{DECODED_TOO_LARGE_PATH}")

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.buffered_response_bytes == 0
    assert stats.buffered_response_budget_rejections == 1
