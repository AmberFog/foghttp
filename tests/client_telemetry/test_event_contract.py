import pytest

import foghttp
from foghttp._client.telemetry import TelemetryDispatcher, start_request_telemetry
from foghttp._telemetry import TELEMETRY_EVENT_SCHEMA_VERSION
from foghttp.methods import GET
from foghttp.telemetry import TelemetryConfig, TelemetryEvent, TelemetryEventType, TelemetryRequestMode
from tests.client_telemetry.models import RecordingTelemetrySink


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://example.com:443/path?token=secret", id="default-port"),
        pytest.param("http://[::1]:80/path", id="ipv6-default-port"),
        pytest.param("https://example.com:444/path", id="non-default-port"),
    ],
)
def test_request_origin_matches_url_model(url: str) -> None:
    sink = RecordingTelemetrySink()
    dispatcher = TelemetryDispatcher(TelemetryConfig(sink=sink))
    telemetry_context = dispatcher.request_context(
        foghttp.Request(GET, url),
        mode=TelemetryRequestMode.BUFFERED,
    )

    assert start_request_telemetry(telemetry_context)

    assert sink.events[0].origin == foghttp.URL(url).origin


def test_event_schema_uses_event_constant() -> None:
    event = TelemetryEvent(
        event_type=TelemetryEventType.REQUEST_STARTED,
        event_sequence=1,
        observed_at_ns=1,
    )

    assert event.schema_version == TELEMETRY_EVENT_SCHEMA_VERSION


def test_request_redacts_url_secret_parts() -> None:
    redacted_url = _start_event_redacted_url(_url_with_secret_parts())
    assert redacted_url is not None
    assert "<redacted>@example.com" in redacted_url
    assert "hunter" not in redacted_url
    assert "secret" not in redacted_url


def _start_event_redacted_url(url: str) -> str | None:
    sink = RecordingTelemetrySink()
    telemetry_context = TelemetryDispatcher(TelemetryConfig(sink=sink)).request_context(
        foghttp.Request(GET, url),
        mode=TelemetryRequestMode.BUFFERED,
    )
    assert start_request_telemetry(telemetry_context)
    return sink.events[0].redacted_url


def _url_with_secret_parts() -> str:
    userinfo = "user:hunter"
    return f"https://{userinfo}@example.com/path?token=secret#section?password=secret"
