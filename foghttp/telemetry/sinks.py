__all__ = ("TelemetryEventSink",)

from typing import Protocol

from .events import TelemetryEvent


class TelemetryEventSink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...
