"""Typed telemetry event contract."""

__all__ = (
    "TelemetryConfig",
    "TelemetryEvent",
    "TelemetryEventSink",
    "TelemetryEventType",
    "TelemetryHookError",
    "TelemetryHookErrorPolicy",
    "TelemetryRequestMode",
    "TelemetryRequestOutcome",
)

from .config import TelemetryConfig, TelemetryHookErrorPolicy
from .errors import TelemetryHookError
from .events import TelemetryEvent, TelemetryEventType, TelemetryRequestMode, TelemetryRequestOutcome
from .sinks import TelemetryEventSink
