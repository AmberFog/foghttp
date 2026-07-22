__all__ = ("TelemetryRequestContext",)

from dataclasses import dataclass
from typing import Protocol

from ...retry_trace import RetryAttempt
from ...telemetry import TelemetryEventType
from .clock import elapsed_seconds_to_ns
from .emission import (
    TelemetryCompletion,
    TelemetryContextData,
    TelemetryEmission,
    TelemetryRedirect,
    TelemetryResponseMetadata,
)


class TelemetryEmitter(Protocol):
    def emit(self, context: TelemetryContextData, emission: TelemetryEmission) -> None: ...


@dataclass(frozen=True, slots=True)
class TelemetryRequestContext:
    dispatcher: TelemetryEmitter
    data: TelemetryContextData

    def request_started(self) -> None:
        self.dispatcher.emit(
            self.data,
            TelemetryEmission(event_type=TelemetryEventType.REQUEST_STARTED),
        )

    def redirect_decision(self, redirect: TelemetryRedirect) -> None:
        self.dispatcher.emit(
            self.data,
            TelemetryEmission(
                event_type=TelemetryEventType.REDIRECT_DECISION,
                status_code=redirect.response.status_code,
                elapsed_ns=redirect.response.elapsed_ns,
                redirect_hop=redirect.redirect_hop,
                origin=redirect.response.origin,
                redacted_url=redirect.response.redacted_url,
            ),
        )

    def retry_decision(
        self,
        retry: RetryAttempt,
        *,
        suppress_hook_errors: bool,
    ) -> None:
        decision_elapsed = retry.decision_elapsed
        if decision_elapsed is None:
            msg = "retry decision record is missing decision_elapsed"
            raise RuntimeError(msg)
        decision_error_type = retry.error_type if retry.status_code is None else None
        self.dispatcher.emit(
            self.data,
            TelemetryEmission(
                event_type=TelemetryEventType.RETRY_DECISION,
                method=retry.method,
                status_code=retry.status_code,
                elapsed_ns=elapsed_seconds_to_ns(decision_elapsed),
                retry_attempt=retry.attempt,
                retry_decision=retry.decision,
                retry_reason=retry.reason,
                retry_backoff_ns=elapsed_seconds_to_ns(retry.backoff),
                origin=retry.origin,
                redacted_url=retry.origin,
                error_type=decision_error_type,
                suppress_hook_errors=suppress_hook_errors,
            ),
        )

    def response_headers_received(self, response: TelemetryResponseMetadata) -> None:
        self.dispatcher.emit(
            self.data,
            TelemetryEmission(
                event_type=TelemetryEventType.RESPONSE_HEADERS_RECEIVED,
                status_code=response.status_code,
                elapsed_ns=response.elapsed_ns,
                origin=response.origin,
                redacted_url=response.redacted_url,
            ),
        )

    def response_body_finished(self, completion: TelemetryCompletion) -> None:
        self.dispatcher.emit(
            self.data,
            self._completion_emission(
                event_type=TelemetryEventType.RESPONSE_BODY_FINISHED,
                completion=completion,
            ),
        )

    def request_finished(self, completion: TelemetryCompletion) -> None:
        self.dispatcher.emit(
            self.data,
            self._completion_emission(
                event_type=TelemetryEventType.REQUEST_FINISHED,
                completion=completion,
            ),
        )

    def _completion_emission(
        self,
        *,
        event_type: TelemetryEventType,
        completion: TelemetryCompletion,
    ) -> TelemetryEmission:
        response = completion.response
        return TelemetryEmission(
            event_type=event_type,
            status_code=None if response is None else response.status_code,
            elapsed_ns=None if response is None else response.elapsed_ns,
            origin=None if response is None else response.origin,
            redacted_url=None if response is None else response.redacted_url,
            outcome=completion.outcome,
            error=completion.error,
            suppress_hook_errors=completion.suppress_hook_errors,
        )
