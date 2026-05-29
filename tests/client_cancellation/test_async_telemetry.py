import asyncio

import pytest

import foghttp
from foghttp.telemetry import TelemetryConfig, TelemetryEventType, TelemetryRequestOutcome
from tests.client_cancellation.constants import SLOW_HEADERS_PATH
from tests.client_telemetry.assertions import assert_event_sequence_is_monotonic, assert_single_request_id
from tests.client_telemetry.models import RecordingTelemetrySink


CANCELLATION_SETTLE_DELAY = 0.05


async def test_async_cancel_emits_cancelled_outcome(cancellation_server: str) -> None:
    sink = RecordingTelemetrySink()

    async with foghttp.AsyncClient(telemetry=TelemetryConfig(sink=sink)) as client:
        task = asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH))
        await asyncio.sleep(CANCELLATION_SETTLE_DELAY)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert tuple(event.event_type for event in sink.events) == (
        TelemetryEventType.REQUEST_STARTED,
        TelemetryEventType.REQUEST_FINISHED,
    )
    assert_event_sequence_is_monotonic(sink.events)
    assert_single_request_id(sink.events)
    assert sink.events[-1].outcome == TelemetryRequestOutcome.CANCELLED
    assert sink.events[-1].error_type == "CancelledError"
