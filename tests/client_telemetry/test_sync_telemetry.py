import pytest

import foghttp
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from foghttp.telemetry import (
    TelemetryConfig,
    TelemetryHookError,
)
from tests.client_telemetry.assertions import (
    assert_buffered_redirect_contract,
    assert_event_sequence_is_monotonic,
    assert_event_types,
    assert_single_request_id,
)
from tests.client_telemetry.constants import BUFFERED_REDIRECT_EVENT_TYPES
from tests.client_telemetry.models import FailingTelemetrySink, RecordingTelemetrySink


def test_sync_buffered_events_are_redacted(sync_http_server: str) -> None:
    sink = RecordingTelemetrySink()

    with foghttp.Client(follow_redirects=True, telemetry=TelemetryConfig(sink=sink)) as client:
        response = client.get(f"{sync_http_server}/redirect/{FOUND}?token=secret")

    assert response.status_code == OK
    assert_event_types(sink.events, BUFFERED_REDIRECT_EVENT_TYPES)
    assert_event_sequence_is_monotonic(sink.events)
    assert_single_request_id(sink.events)
    assert_buffered_redirect_contract(sink.events)


def test_sync_hook_raise_maps_to_public_error(sync_http_server: str) -> None:
    with (
        foghttp.Client(telemetry=TelemetryConfig(sink=FailingTelemetrySink())) as client,
        pytest.raises(
            TelemetryHookError,
        ),
    ):
        client.get(f"{sync_http_server}/status/{OK}")


def test_sync_hook_warn_keeps_request_running(sync_http_server: str) -> None:
    with (
        foghttp.Client(
            telemetry=TelemetryConfig(
                sink=FailingTelemetrySink(),
                on_hook_error="warn",
            ),
        ) as client,
        pytest.warns(RuntimeWarning, match="telemetry event sink failed"),
    ):
        response = client.get(f"{sync_http_server}/status/{OK}")

    assert response.status_code == OK
