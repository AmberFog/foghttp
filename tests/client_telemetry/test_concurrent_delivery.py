from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import foghttp
from foghttp.status_codes.success import OK
from tests.client_telemetry.assertions import assert_event_sequences_are_unique
from tests.client_telemetry.constants import BUFFERED_EVENT_TYPES
from tests.client_telemetry.models import ThreadSafeTelemetrySink


_CONCURRENT_REQUESTS = 4


def test_sync_concurrent_requests_emit_unique_ids(sync_http_server: str) -> None:
    sink = ThreadSafeTelemetrySink()
    start_barrier = Barrier(_CONCURRENT_REQUESTS)

    with (
        foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=sink)) as client,
        ThreadPoolExecutor(max_workers=_CONCURRENT_REQUESTS) as executor,
    ):
        responses = tuple(
            executor.map(
                _get_ok_response,
                (client,) * _CONCURRENT_REQUESTS,
                (sync_http_server,) * _CONCURRENT_REQUESTS,
                range(_CONCURRENT_REQUESTS),
                (start_barrier,) * _CONCURRENT_REQUESTS,
            ),
        )

    assert tuple(response.status_code for response in responses) == (OK,) * _CONCURRENT_REQUESTS
    assert len(sink.events) == _expected_event_count()
    assert_event_sequences_are_unique(sink.events)
    assert len({event.request_id for event in sink.events}) == _CONCURRENT_REQUESTS


def _get_ok_response(
    client: foghttp.Client,
    base_url: str,
    request_index: int,
    start_barrier: Barrier,
) -> foghttp.Response:
    start_barrier.wait()
    return client.get(f"{base_url}/status/{OK}?request={request_index}")


def _expected_event_count() -> int:
    return len(BUFFERED_EVENT_TYPES) * _CONCURRENT_REQUESTS
