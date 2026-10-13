import pytest

import foghttp
from tests.support.transport_stats import wait_for_sync_transport_stats

from .constants import GZIP_RESERVATION, IDENTITY_RESERVATION
from .limit_cases import CAPPED_FAILURES, CAPPED_SUCCESSES
from .payloads import EncodedResponse, gated_gzip, gzip_bytes
from .read_actions import collect_sync_into
from .server import ServerFactory


@pytest.mark.parametrize(("case", "cap", "expected"), CAPPED_SUCCESSES)
def test_sync_output_cap_success(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    cap: int | None,
    expected: bytes,
) -> None:
    server = decompression_server(case)
    limits = foghttp.Limits(max_stream_decoded_bytes=cap, max_response_body_size=0, max_buffered_response_bytes=0)
    with (
        foghttp.Client(limits=limits, trust_env=False) as client,
        client.stream("GET", server.url, decode_content=True) as response,
    ):
        assert b"".join(response.iter_bytes()) == expected
        assert client.stats().buffered_response_bytes == 0
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(("case", "cap"), CAPPED_FAILURES)
def test_sync_output_cap_failure_never_exposes_excess(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    cap: int,
) -> None:
    server = decompression_server(case)
    delivered = bytearray()
    with foghttp.Client(limits=foghttp.Limits(max_stream_decoded_bytes=cap), trust_env=False) as client:
        with (
            client.stream("GET", server.url, decode_content=True) as response,
            pytest.raises(foghttp.ResponseBodyTooLargeError),
        ):
            collect_sync_into(response.iter_bytes(), delivered)
        assert len(delivered) <= cap
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.stream_decoder_reserved_bytes == 0 and stats.active_requests == 0,
            message="size-limit failure retained decoded resources",
        )


@pytest.mark.parametrize("encodings", [(), ("gzip",)])
def test_sync_zero_budget_rejects_body_bearing_mode(
    decompression_server: ServerFactory,
    encodings: tuple[str, ...],
) -> None:
    server = decompression_server(EncodedResponse(gzip_bytes(b""), encodings))
    with foghttp.Client(limits=foghttp.Limits(max_stream_decoder_memory_bytes=0), trust_env=False) as client:
        with (
            pytest.raises(foghttp.ResponseBodyBudgetExceededError),
            client.stream(
                "GET",
                server.url,
                decode_content=True,
            ),
        ):
            pytest.fail("zero decoder budget must reject before response exposure")
        assert client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize(
    ("case", "reservation"),
    [(gated_gzip(), GZIP_RESERVATION), (EncodedResponse(b"x", ()), IDENTITY_RESERVATION)],
)
@pytest.mark.parametrize("admitted_streams", [1, 2])
def test_sync_aggregate_budget_admission_and_recovery(
    decompression_server: ServerFactory,
    case: EncodedResponse,
    reservation: int,
    admitted_streams: int,
) -> None:
    server = decompression_server(case)
    limits = foghttp.Limits(max_stream_decoder_memory_bytes=reservation * admitted_streams)
    with foghttp.Client(limits=limits, trust_env=False) as client:
        with client.stream("GET", server.url, decode_content=True) as first:
            assert client.stats().stream_decoder_reserved_bytes == reservation
            if admitted_streams == 1:
                with (
                    pytest.raises(foghttp.ResponseBodyBudgetExceededError),
                    client.stream(
                        "GET",
                        server.url,
                        decode_content=True,
                    ),
                ):
                    pytest.fail("competing stream exceeded the aggregate reservation")
            else:
                with client.stream("GET", server.url, decode_content=True):
                    assert client.stats().stream_decoder_reserved_bytes == 2 * reservation
                assert client.stats().stream_decoder_reserved_bytes == reservation
            assert client.stats().stream_decoder_reserved_bytes == reservation
            assert client.stats().buffered_response_bytes == 0
            first.close()
            first.close()
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.stream_decoder_reserved_bytes == 0 and stats.active_requests == 0,
            message="closed competing streams must return their budget",
        )
        server.release_tail.set()
        with client.stream("GET", server.url, decode_content=True) as recovered:
            assert b"".join(recovered.iter_bytes())
        assert client.stats().stream_decoder_reserved_bytes == 0
