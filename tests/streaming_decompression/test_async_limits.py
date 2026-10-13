import pytest

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats

from .constants import GZIP_RESERVATION, IDENTITY_RESERVATION
from .limit_cases import CAPPED_FAILURES, CAPPED_SUCCESSES
from .payloads import EncodedResponse, gated_gzip, gzip_bytes
from .read_actions import collect_async_into
from .server import ServerFactory


@pytest.mark.parametrize(("case", "cap", "expected"), CAPPED_SUCCESSES)
async def test_async_output_cap_success(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    cap: int | None,
    expected: bytes,
) -> None:
    server = decompression_server(case)
    limits = foghttp.Limits(max_stream_decoded_bytes=cap, max_response_body_size=0, max_buffered_response_bytes=0)
    async with (
        foghttp.AsyncClient(limits=limits, trust_env=False) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == expected
        assert client.stats().buffered_response_bytes == 0
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(("case", "cap"), CAPPED_FAILURES)
async def test_async_output_cap_failure_never_exposes_excess(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    cap: int,
) -> None:
    server = decompression_server(case)
    delivered = bytearray()
    async with foghttp.AsyncClient(limits=foghttp.Limits(max_stream_decoded_bytes=cap), trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as response:
            with pytest.raises(foghttp.ResponseBodyTooLargeError):
                await collect_async_into(response.aiter_bytes(), delivered)
        assert len(delivered) <= cap
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.stream_decoder_reserved_bytes == 0 and stats.active_requests == 0,
            message="size-limit failure retained decoded resources",
        )


@pytest.mark.parametrize("encodings", [(), ("gzip",)])
async def test_async_zero_budget_rejects_body_bearing_mode(
    decompression_server: ServerFactory,
    encodings: tuple[str, ...],
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(b""), encodings))
    async with foghttp.AsyncClient(limits=foghttp.Limits(max_stream_decoder_memory_bytes=0), trust_env=False) as client:
        with pytest.raises(foghttp.ResponseBodyBudgetExceededError):
            async with client.stream("GET", server.url, decode_content=True):
                pytest.fail("zero decoder budget must reject before response exposure")
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(
    ("case", "reservation"),
    [(gated_gzip(), GZIP_RESERVATION), (EncodedResponse(b"x", ()), IDENTITY_RESERVATION)],
)
@pytest.mark.parametrize("admitted_streams", [1, 2])
async def test_async_aggregate_budget_admission_and_recovery(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    reservation: int,
    admitted_streams: int,
) -> None:
    server = decompression_server(case)
    limits = foghttp.Limits(max_stream_decoder_memory_bytes=reservation * admitted_streams)
    async with foghttp.AsyncClient(limits=limits, trust_env=False) as client:
        async with client.stream("GET", server.url, decode_content=True) as first:
            assert client.stats().stream_decoder_reserved_bytes == reservation
            if admitted_streams == 1:
                with pytest.raises(foghttp.ResponseBodyBudgetExceededError):
                    async with client.stream("GET", server.url, decode_content=True):
                        pytest.fail("competing stream exceeded the aggregate reservation")
            else:
                async with client.stream("GET", server.url, decode_content=True):
                    assert client.stats().stream_decoder_reserved_bytes == 2 * reservation
                assert client.stats().stream_decoder_reserved_bytes == reservation
            assert client.stats().stream_decoder_reserved_bytes == reservation
            assert client.stats().buffered_response_bytes == 0
            await first.aclose()
            await first.aclose()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.stream_decoder_reserved_bytes == 0 and stats.active_requests == 0,
            message="closed competing streams must return their budget",
        )
        server.release_tail.set()
        async with client.stream("GET", server.url, decode_content=True) as recovered:
            assert b"".join([chunk async for chunk in recovered.aiter_bytes()])
        assert client.stats().stream_decoder_reserved_bytes == 0
