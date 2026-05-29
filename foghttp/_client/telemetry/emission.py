__all__ = (
    "TelemetryCompletion",
    "TelemetryContextData",
    "TelemetryEmission",
    "TelemetryRedirect",
    "TelemetryResponseMetadata",
)

from dataclasses import dataclass

from ...telemetry import TelemetryEventType, TelemetryRequestMode, TelemetryRequestOutcome


@dataclass(frozen=True, slots=True)
class TelemetryContextData:
    request_id: int
    mode: TelemetryRequestMode
    method: str
    origin: str | None
    redacted_url: str


@dataclass(frozen=True, slots=True)
class TelemetryResponseMetadata:
    status_code: int
    elapsed_ns: int | None
    origin: str | None
    redacted_url: str


@dataclass(frozen=True, slots=True)
class TelemetryRedirect:
    response: TelemetryResponseMetadata
    redirect_hop: int


@dataclass(frozen=True, slots=True)
class TelemetryCompletion:
    response: TelemetryResponseMetadata | None
    outcome: TelemetryRequestOutcome
    error: BaseException | None = None
    suppress_hook_errors: bool = False


@dataclass(frozen=True, slots=True)
class TelemetryEmission:
    event_type: TelemetryEventType
    status_code: int | None = None
    elapsed_ns: int | None = None
    redirect_hop: int | None = None
    origin: str | None = None
    redacted_url: str | None = None
    outcome: TelemetryRequestOutcome | None = None
    error: BaseException | None = None
    suppress_hook_errors: bool = False
