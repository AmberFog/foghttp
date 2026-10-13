import pytest

import foghttp
from tests.client_telemetry.assertions import assert_stream_completion
from tests.client_telemetry.models import FailOnEventTelemetrySink, RecordingTelemetrySink
from tests.support.transport_stats import wait_for_sync_transport_stats

from .constants import DECODED_BODY, FIRST_OUTPUT, TAIL_OUTPUT
from .payloads import EncodedResponse, gated_gzip, gzip_bytes
from .read_actions import collect_sync_into, read_sync_prefix
from .server import ServerFactory


@pytest.mark.parametrize("decode_content", [False, True], ids=["raw", "decoded"])
def test_sync_telemetry_counts_selected_representation(
    decompression_server: ServerFactory,
    *,
    decode_content: bool,
) -> None:
    encoded = gzip_bytes(DECODED_BODY)
    server = decompression_server(EncodedResponse(encoded))
    sink = RecordingTelemetrySink()
    with (
        foghttp.Client(trust_env=False, telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        client.stream("GET", server.url, decode_content=decode_content) as response,
    ):
        delivered = b"".join(response.iter_bytes())
    expected = DECODED_BODY if decode_content else encoded
    assert delivered == expected
    assert_stream_completion(sink.events, outcome=foghttp.TelemetryRequestOutcome.SUCCESS)
    terminal = [
        event
        for event in sink.events
        if event.event_type
        in {foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED, foghttp.TelemetryEventType.REQUEST_FINISHED}
    ]
    assert [event.response_body_bytes for event in terminal] == [len(delivered), len(delivered)]


def test_sync_decode_error_survives_failing_hook_and_is_not_retried(decompression_server: ServerFactory) -> None:
    case = gated_gzip()
    server = decompression_server(EncodedResponse(case.body[:-1], gate_after=case.gate_after))
    sink = FailOnEventTelemetrySink(foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED)
    delivered = bytearray()
    with foghttp.Client(
        trust_env=False,
        retry=foghttp.RetryPolicy(retries=2, backoff=0, jitter=0),
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        with client.stream("GET", server.url, decode_content=True) as response:
            iterator = response.iter_bytes()
            delivered.extend(read_sync_prefix(iterator, len(FIRST_OUTPUT)))
            assert delivered == FIRST_OUTPUT
            server.release_tail.set()
            with pytest.raises(foghttp.ResponseDecodingError) as error:
                collect_sync_into(iterator, delivered)
            response.close()
            response.close()
            assert error.value.__cause__ is not None
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.stream_decoder_reserved_bytes == 0,
            message="failed hook must not retain decoder resources",
        )
        assert client.stats().failed_requests == 1
    assert (FIRST_OUTPUT + TAIL_OUTPUT).startswith(delivered)
    assert server.state.snapshot().request_count == 1
    assert_stream_completion(
        sink.events,
        outcome=foghttp.TelemetryRequestOutcome.ERROR,
        error_type="ResponseDecodingError",
    )
    finished = [event for event in sink.events if event.event_type == foghttp.TelemetryEventType.REQUEST_FINISHED]
    assert finished[0].response_body_bytes == len(delivered)
