import foghttp
from foghttp.status_codes.success import OK
from foghttp.telemetry import TelemetryConfig, TelemetryRequestMode, TelemetryRequestOutcome
from tests.client_telemetry.assertions import (
    assert_event_sequence_is_monotonic,
    assert_event_types,
    assert_single_request_id,
)
from tests.client_telemetry.models import RecordingTelemetrySink


async def test_async_buffered_core_events(http_server: str) -> None:
    sink = RecordingTelemetrySink()

    async with foghttp.AsyncClient(telemetry=TelemetryConfig(sink=sink)) as client:
        response = await client.get(f"{http_server}/status/{OK}")

    assert response.status_code == OK
    assert_event_types(
        sink.events,
        (
            foghttp.TelemetryEventType.REQUEST_STARTED,
            foghttp.TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
            foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED,
            foghttp.TelemetryEventType.REQUEST_FINISHED,
        ),
    )
    assert_event_sequence_is_monotonic(sink.events)
    assert_single_request_id(sink.events)
    assert sink.events[0].mode == TelemetryRequestMode.BUFFERED
    assert sink.events[-1].outcome == TelemetryRequestOutcome.SUCCESS
