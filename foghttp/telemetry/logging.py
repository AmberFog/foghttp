__all__ = ("StructuredLoggingTelemetrySink",)

import logging

from ..errors.timeout import ConnectTimeout, PoolTimeout, ReadTimeout, TimeoutError, WriteTimeout
from ..url import URL
from .events import TelemetryEvent, TelemetryEventType


_LOGGER_NAME = "foghttp.lifecycle"
_LOGGED_EVENT_TYPES: frozenset[TelemetryEventType] = frozenset(
    (
        TelemetryEventType.CONNECTION_OPENED,
        TelemetryEventType.CONNECTION_OPEN_FAILED,
        TelemetryEventType.CONNECTION_REUSED,
        TelemetryEventType.CONNECTION_CLOSED,
        TelemetryEventType.CONNECTION_ABORTED,
        TelemetryEventType.REDIRECT_DECISION,
        TelemetryEventType.RETRY_DECISION,
    ),
)
_TIMEOUT_ERROR_TYPES = frozenset(
    error_type.__name__
    for error_type in (
        ConnectTimeout,
        PoolTimeout,
        ReadTimeout,
        TimeoutError,
        WriteTimeout,
    )
)


class StructuredLoggingTelemetrySink:
    """Write selected lifecycle telemetry to ``foghttp.lifecycle`` at DEBUG."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(_LOGGER_NAME)

    def emit(self, event: TelemetryEvent) -> None:
        if not self._logger.isEnabledFor(logging.DEBUG) or not _is_logged_event(event):
            return

        self._logger.debug(
            "FogHTTP lifecycle event: %s",
            event.event_type.value,
            extra=_log_fields(event),
        )


def _is_logged_event(event: TelemetryEvent) -> bool:
    if event.event_type in _LOGGED_EVENT_TYPES:
        return True
    return event.event_type is TelemetryEventType.REQUEST_FINISHED and (
        event.timeout_phase is not None or event.error_type in _TIMEOUT_ERROR_TYPES
    )


def _log_fields(event: TelemetryEvent) -> dict[str, object]:
    return {
        "foghttp_event_type": event.event_type.value,
        "foghttp_schema_version": event.schema_version,
        "foghttp_event_sequence": event.event_sequence,
        "foghttp_observed_at_ns": event.observed_at_ns,
        "foghttp_request_id": event.request_id,
        "foghttp_mode": None if event.mode is None else event.mode.value,
        "foghttp_method": event.method,
        "foghttp_origin": _normalized_origin(event.origin),
        "foghttp_status_code": event.status_code,
        "foghttp_elapsed_ns": event.elapsed_ns,
        "foghttp_redirect_hop": event.redirect_hop,
        "foghttp_retry_attempt": event.retry_attempt,
        "foghttp_retry_decision": None if event.retry_decision is None else event.retry_decision.value,
        "foghttp_retry_reason": None if event.retry_reason is None else event.retry_reason.value,
        "foghttp_retry_backoff_ns": event.retry_backoff_ns,
        "foghttp_outcome": None if event.outcome is None else event.outcome.value,
        "foghttp_error_type": event.error_type,
        "foghttp_timeout_phase": event.timeout_phase,
    }


def _normalized_origin(origin: str | None) -> str | None:
    if origin is None:
        return None
    try:
        return URL(origin).origin
    except ValueError:
        return None
