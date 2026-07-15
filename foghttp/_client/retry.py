__all__ = (
    "RetryDecisionData",
    "bind_retry_decisions",
    "public_retry_decisions",
    "raw_retry_decisions_on_error",
    "retry_decisions_from_raw",
)

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..telemetry import TelemetryRetryDecision, TelemetryRetryReason


_RETRY_DECISIONS_ATTRIBUTE = "_foghttp_retry_decisions"
_PUBLIC_RETRY_DECISIONS_ATTRIBUTE = "_retry_decisions"
_TargetT = TypeVar("_TargetT")


class RawRetryDecisionSource(Protocol):
    @property
    def retry_decisions(self) -> Sequence["_foghttp.RawRetryDecision"]: ...


@dataclass(frozen=True, slots=True)
class RetryDecisionData:
    attempt: int
    method: str
    origin: str
    status_code: int | None
    error_type: str | None
    decision: TelemetryRetryDecision
    reason: TelemetryRetryReason
    backoff: float
    elapsed: float


def retry_decisions_from_raw(source: RawRetryDecisionSource) -> tuple[RetryDecisionData, ...]:
    return tuple(_retry_decision_from_raw(decision) for decision in source.retry_decisions)


def bind_retry_decisions(target: _TargetT, decisions: tuple[RetryDecisionData, ...]) -> _TargetT:
    if decisions:
        object.__setattr__(target, _PUBLIC_RETRY_DECISIONS_ATTRIBUTE, decisions)
    return target


def public_retry_decisions(source: object) -> tuple[RetryDecisionData, ...]:
    raw_decisions = raw_retry_decisions_on_error(source)
    if raw_decisions:
        return raw_decisions
    decisions = getattr(source, _PUBLIC_RETRY_DECISIONS_ATTRIBUTE, None)
    if isinstance(decisions, tuple) and all(isinstance(decision, RetryDecisionData) for decision in decisions):
        return decisions
    return ()


def raw_retry_decisions_on_error(error: object) -> tuple[RetryDecisionData, ...]:
    raw_decisions = getattr(error, _RETRY_DECISIONS_ATTRIBUTE, ())
    if not isinstance(raw_decisions, tuple) or not all(
        isinstance(decision, _foghttp.RawRetryDecision) for decision in raw_decisions
    ):
        return ()
    return tuple(_retry_decision_from_raw(decision) for decision in raw_decisions)


def _retry_decision_from_raw(raw: "_foghttp.RawRetryDecision") -> RetryDecisionData:
    return RetryDecisionData(
        attempt=raw.attempt,
        method=raw.method,
        origin=raw.origin,
        status_code=raw.status_code,
        error_type=raw.error_type,
        decision=TelemetryRetryDecision(raw.decision),
        reason=TelemetryRetryReason(raw.reason),
        backoff=raw.backoff,
        elapsed=raw.elapsed,
    )
