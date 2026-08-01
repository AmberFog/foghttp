import foghttp


class RecordingTelemetrySink:
    def __init__(self) -> None:
        self.events: list[foghttp.TelemetryEvent] = []

    def emit(self, event: foghttp.TelemetryEvent) -> None:
        self.events.append(event)


def test_telemetry_sink_is_a_structural_public_contract() -> None:
    sink: foghttp.TelemetryEventSink = RecordingTelemetrySink()
    event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.REQUEST_STARTED,
        event_sequence=1,
        observed_at_ns=1,
    )

    sink.emit(event)

    assert isinstance(sink, RecordingTelemetrySink)
    assert sink.events == [event]
