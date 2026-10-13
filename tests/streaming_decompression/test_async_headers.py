from http import HTTPStatus

import pytest

import foghttp
from tests.client_telemetry.assertions import assert_connection_abort, assert_stream_request_failure
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.transport_stats import wait_for_async_transport_stats

from .cases import INVALID_PLANS
from .constants import DECODED_BODY
from .payloads import EncodedResponse, gzip_bytes
from .server import ServerFactory


@pytest.mark.parametrize("encodings", INVALID_PLANS)
async def test_async_invalid_plan_fails_before_exposure(
    decompression_server: ServerFactory,
    encodings: tuple[str, ...],
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(DECODED_BODY), encodings, gate_after=0))
    sink = RecordingTelemetrySink()
    async with foghttp.AsyncClient(trust_env=False, telemetry=foghttp.TelemetryConfig(sink=sink)) as client:
        with pytest.raises(foghttp.ResponseDecodingError):
            async with client.stream("GET", server.url, decode_content=True):
                pytest.fail("invalid coding plan was exposed to the caller")
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="rejected plan must not leak resources",
        )
    assert foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED not in [event.event_type for event in sink.events]
    assert_stream_request_failure(sink.events, error_type="ResponseDecodingError")
    assert_connection_abort(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ResponseDecodingError",
    )


@pytest.mark.parametrize(("method", "status"), [("HEAD", 200), ("GET", 204), ("GET", 205), ("GET", 304)])
async def test_async_no_body_bypasses_invalid_coding_and_zero_budget(
    decompression_server: ServerFactory,
    method: str,
    status: int,
) -> None:
    server = decompression_server(EncodedResponse(b"", ("unknown;parameter=yes",), status))
    limits = foghttp.Limits(max_stream_decoder_memory_bytes=0)
    async with (
        foghttp.AsyncClient(limits=limits, trust_env=False) as client,
        client.stream(method, server.url, decode_content=True) as response,
    ):
        assert response.status_code == status
        assert response.headers["content-encoding"] == "unknown;parameter=yes"
        assert response.headers["content-length"] == "0"
        assert [chunk async for chunk in response.aiter_bytes()] == []
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize("encodings", [(), ("",), (" , identity, , IDENTITY",)])
async def test_async_identity_retains_headers_including_206(
    decompression_server: ServerFactory,
    encodings: tuple[str, ...],
) -> None:
    server = decompression_server(EncodedResponse(DECODED_BODY, encodings, HTTPStatus.PARTIAL_CONTENT))
    async with (
        foghttp.AsyncClient(trust_env=False) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        expected_encoding = encodings[0].strip(" \t") if encodings else None
        assert response.status_code == HTTPStatus.PARTIAL_CONTENT
        assert response.headers.get("content-encoding") == expected_encoding
        assert response.headers["content-length"] == str(len(DECODED_BODY))
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == DECODED_BODY


async def test_async_compressed_206_rejected_but_raw_works(decompression_server: ServerFactory) -> None:
    encoded = gzip_bytes(DECODED_BODY)
    server = decompression_server(EncodedResponse(encoded, status=HTTPStatus.PARTIAL_CONTENT))
    async with foghttp.AsyncClient(trust_env=False) as client:
        with pytest.raises(foghttp.ResponseDecodingError):
            async with client.stream("GET", server.url, decode_content=True):
                pytest.fail("compressed partial representation must fail on entry")
        async with client.stream("GET", server.url) as response:
            assert b"".join([chunk async for chunk in response.aiter_bytes()]) == encoded


@pytest.mark.parametrize(
    ("encodings", "error_type"),
    [
        (("zstd",), foghttp.ResponseDecodingError),
        (("gzip",), foghttp.ResponseBodyBudgetExceededError),
        ((), foghttp.ResponseBodyBudgetExceededError),
    ],
)
async def test_async_entry_failure_preserves_already_clean_transport(
    decompression_server: ServerFactory,
    encodings: tuple[str, ...],
    error_type: type[foghttp.ResponseError],
) -> None:
    server = decompression_server(EncodedResponse(b"", encodings))
    sink = RecordingTelemetrySink()
    async with foghttp.AsyncClient(
        limits=foghttp.Limits(max_stream_decoder_memory_bytes=0),
        telemetry=foghttp.TelemetryConfig(sink=sink),
        trust_env=False,
    ) as client:
        with pytest.raises(error_type):
            async with client.stream("GET", server.url, decode_content=True):
                pytest.fail("invalid decoded response was exposed")
        stats = client.stats()
        assert stats.failed_requests == 1
        assert stats.active_requests == stats.stream_decoder_reserved_bytes == 0
        assert stats.response_body_aborted == stats.connections_aborted == 0
        assert stats.response_body_reuse_eligible == 1
        assert_stream_request_failure(sink.events, error_type=error_type.__name__)
        assert (await client.get(f"{server.url}/healthy")).content == b"healthy"
        assert server.state.snapshot().connection_count == 1
        assert client.stats().connections_reused == 1
