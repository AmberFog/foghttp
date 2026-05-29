from dataclasses import dataclass, field
import threading

from foghttp.telemetry import TelemetryEvent, TelemetryEventType


@dataclass(slots=True)
class RecordingTelemetrySink:
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)


@dataclass(slots=True)
class ThreadSafeTelemetrySink:
    events: list[TelemetryEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def emit(self, event: TelemetryEvent) -> None:
        with self._lock:
            self.events.append(event)


@dataclass(slots=True)
class FailOnEventTelemetrySink:
    fail_on: TelemetryEventType
    events: list[TelemetryEvent] = field(default_factory=list)

    def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
        if event.event_type == self.fail_on:
            raise RuntimeError(event.event_type.value)


class FailingTelemetrySink:
    def emit(self, event: TelemetryEvent) -> None:
        raise RuntimeError(event.event_type.value)
