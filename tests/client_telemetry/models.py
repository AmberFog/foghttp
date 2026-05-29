from dataclasses import dataclass, field

from foghttp.telemetry import TelemetryEvent


@dataclass(slots=True)
class RecordingTelemetrySink:
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)


class FailingTelemetrySink:
    def emit(self, event: TelemetryEvent) -> None:
        raise RuntimeError(event.event_type.value)
