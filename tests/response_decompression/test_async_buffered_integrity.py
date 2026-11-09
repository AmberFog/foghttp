import pytest

from foghttp import AsyncClient, RequestError, _foghttp
from foghttp.status_codes.success import OK
from tests.client_keepalive.assertions import assert_single_connection_snapshot
from tests.streaming_decompression.payloads import EncodedResponse
from tests.streaming_decompression.server import start_decompression_server

from .constants import BODY_CONTENT_TYPE
from .integrity_cases import INVALID_DEFLATE_BODIES, VALID_BUFFERED_BODIES, integrity_limits


@pytest.mark.parametrize("encoded_body", INVALID_DEFLATE_BODIES)
async def test_async_buffered_deflate_error_releases_resources_and_preserves_completed_connection(
    encoded_body: bytes,
) -> None:
    with start_decompression_server(EncodedResponse(encoded_body, ("deflate",))) as server:
        async with AsyncClient(limits=integrity_limits(), trust_env=False) as client:
            with pytest.raises(RequestError, match="failed to decode deflate response body") as exc_info:
                await client.get(server.url)

            failed_stats = client.stats()
            assert type(exc_info.value.__cause__) is _foghttp.FogHttpError
            assert exc_info.value.__cause__.args == (str(exc_info.value),)
            assert failed_stats.total_requests == 1
            assert failed_stats.failed_requests == 1
            assert failed_stats.active_requests == 0
            assert failed_stats.pending_requests == 0
            assert failed_stats.buffered_response_bytes == 0
            assert failed_stats.buffered_response_budget_rejections == 0
            assert failed_stats.response_body_aborted == 1
            assert failed_stats.connections_aborted == 0
            assert failed_stats.connections_closed == 0
            assert failed_stats.connections_opened == 1
            assert failed_stats.active_connections == 1
            assert failed_stats.idle_connections == 1

            recovery = await client.get(f"{server.url}/healthy")
            stats = client.stats()

            assert recovery.status_code == OK
            assert recovery.content == b"healthy"
            assert stats.total_requests == failed_stats.total_requests + 1
            assert stats.failed_requests == 1
            assert stats.active_requests == 0
            assert stats.pending_requests == 0
            assert stats.buffered_response_bytes == 0
            assert stats.response_body_aborted == 1
            assert stats.connections_opened == 1
            assert stats.connections_reused == 1
            assert stats.connections_aborted == 0
            assert stats.connections_closed == 0
            assert_single_connection_snapshot(server.state.snapshot(), stats.total_requests)


@pytest.mark.parametrize(("encoded", "decoded_body"), VALID_BUFFERED_BODIES)
async def test_async_buffered_completion_validation_preserves_valid_content(
    encoded: EncodedResponse,
    decoded_body: bytes,
) -> None:
    with start_decompression_server(encoded) as server:
        async with AsyncClient(limits=integrity_limits(), trust_env=False) as client:
            response = await client.get(server.url)
            stats = client.stats()

    assert response.status_code == OK
    assert response.content == decoded_body
    assert response.headers["content-type"] == BODY_CONTENT_TYPE
    assert "content-encoding" not in response.headers
    assert "content-length" not in response.headers
    assert stats.total_requests == 1
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
    assert stats.buffered_response_bytes == 0
    assert stats.response_body_aborted == 0
