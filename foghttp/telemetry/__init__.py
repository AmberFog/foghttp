"""Typed telemetry event contract."""

__all__ = (
    "StructuredLoggingTelemetrySink",
    "TelemetryConfig",
    "TelemetryEvent",
    "TelemetryEventSink",
    "TelemetryEventType",
    "TelemetryHookError",
    "TelemetryHookErrorPolicy",
    "TelemetryRequestMode",
    "TelemetryRequestOutcome",
    "TelemetryRetryDecision",
    "TelemetryRetryReason",
)

from .config import TelemetryConfig, TelemetryHookErrorPolicy
from .errors import TelemetryHookError
from .events import (
    TelemetryEvent,
    TelemetryEventType,
    TelemetryRequestMode,
    TelemetryRequestOutcome,
    TelemetryRetryDecision,
    TelemetryRetryReason,
)
from .logging import StructuredLoggingTelemetrySink
from .sinks import TelemetryEventSink
