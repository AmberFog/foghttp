__all__ = ("RetryAttempt", "RetryTrace", "RetryTraceOutcome")

from dataclasses import dataclass
from enum import StrEnum

from .telemetry import TelemetryRetryDecision, TelemetryRetryReason


class RetryTraceOutcome(StrEnum):
    RESPONSE = "response"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RetryAttempt:
    attempt: int
    method: str
    origin: str
    redirect_hop: int
    status_code: int | None
    error_type: str | None
    decision: TelemetryRetryDecision | None
    reason: TelemetryRetryReason | None
    backoff: float
    decision_elapsed: float | None
    completed_elapsed: float


@dataclass(frozen=True, slots=True)
class RetryTrace:
    attempts: tuple[RetryAttempt, ...]
    outcome: RetryTraceOutcome
    status_code: int | None
    error_type: str | None
    elapsed: float
