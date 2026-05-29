__all__ = (
    "TelemetryEvent",
    "TelemetryEventType",
    "TelemetryRequestMode",
    "TelemetryRequestOutcome",
)

from dataclasses import dataclass
from enum import StrEnum

from .._telemetry import TELEMETRY_EVENT_SCHEMA_VERSION


class TelemetryEventType(StrEnum):
    REQUEST_STARTED = "request_started"
    POOL_ACQUIRE_STARTED = "pool_acquire_started"
    POOL_ACQUIRE_FINISHED = "pool_acquire_finished"
    CONNECTION_OPENED = "connection_opened"
    CONNECTION_OPEN_FAILED = "connection_open_failed"
    CONNECTION_REUSED = "connection_reused"
    CONNECTION_CLOSED = "connection_closed"
    CONNECTION_ABORTED = "connection_aborted"
    RESPONSE_HEADERS_RECEIVED = "response_headers_received"
    REDIRECT_DECISION = "redirect_decision"
    RESPONSE_BODY_FINISHED = "response_body_finished"
    REQUEST_FINISHED = "request_finished"


class TelemetryRequestMode(StrEnum):
    BUFFERED = "buffered"
    STREAM = "stream"


class TelemetryRequestOutcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event_type: TelemetryEventType
    event_sequence: int
    observed_at_ns: int
    request_id: int | None = None
    mode: TelemetryRequestMode | None = None
    method: str | None = None
    origin: str | None = None
    redacted_url: str | None = None
    status_code: int | None = None
    elapsed_ns: int | None = None
    redirect_hop: int | None = None
    outcome: TelemetryRequestOutcome | None = None
    error_type: str | None = None
    schema_version: int = TELEMETRY_EVENT_SCHEMA_VERSION
