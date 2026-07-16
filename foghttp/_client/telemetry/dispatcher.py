__all__ = ("TelemetryDispatcher",)

from dataclasses import replace
import threading
import time
from typing import NoReturn
import warnings

from ...request import Request
from ...telemetry import (
    TelemetryConfig,
    TelemetryEvent,
    TelemetryEventSink,
    TelemetryHookError,
    TelemetryHookErrorPolicy,
    TelemetryRequestMode,
)
from .emission import TelemetryContextData, TelemetryEmission
from .request_context import TelemetryRequestContext
from .url import redacted_url, url_origin


_HOOK_ERROR_MESSAGE = "telemetry event sink failed"


class TelemetryDispatcher:
    def __init__(self, config: TelemetryConfig | None) -> None:
        self._sink = None if config is None else config.sink
        self._hook_error_policy = "raise" if config is None else config.on_hook_error
        self._lock = threading.Lock()
        self._next_event_sequence = 1
        self._next_request_id = 1

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def request_context(self, request: Request, *, mode: TelemetryRequestMode) -> TelemetryRequestContext | None:
        if self._sink is None:
            return None

        return TelemetryRequestContext(
            dispatcher=self,
            data=TelemetryContextData(
                request_id=self._request_id(),
                mode=mode,
                method=request.method,
                origin=url_origin(request.url),
                redacted_url=redacted_url(request.url),
            ),
        )

    def emit(self, context: TelemetryContextData, emission: TelemetryEmission) -> None:
        sink = self._sink
        if sink is None:
            return

        event = _event_from_emission(
            context=context,
            emission=emission,
            event_sequence=self._event_sequence(),
        )
        _emit_event(
            sink=sink,
            event=event,
            hook_error_policy=self._hook_error_policy,
            suppress_hook_errors=emission.suppress_hook_errors,
        )

    def _event_sequence(self) -> int:
        with self._lock:
            event_sequence = self._next_event_sequence
            self._next_event_sequence += 1
            return event_sequence

    def _request_id(self) -> int:
        with self._lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            return request_id


def _event_from_emission(
    *,
    context: TelemetryContextData,
    emission: TelemetryEmission,
    event_sequence: int,
) -> TelemetryEvent:
    event_context = _context_with_emission_overrides(context, emission)
    return TelemetryEvent(
        event_type=emission.event_type,
        event_sequence=event_sequence,
        observed_at_ns=time.perf_counter_ns(),
        request_id=event_context.request_id,
        mode=event_context.mode,
        method=event_context.method,
        origin=event_context.origin,
        redacted_url=event_context.redacted_url,
        status_code=emission.status_code,
        elapsed_ns=emission.elapsed_ns,
        redirect_hop=emission.redirect_hop,
        retry_attempt=emission.retry_attempt,
        retry_decision=emission.retry_decision,
        retry_reason=emission.retry_reason,
        retry_backoff_ns=emission.retry_backoff_ns,
        outcome=emission.outcome,
        error_type=_emission_error_type(emission),
    )


def _emission_error_type(emission: TelemetryEmission) -> str | None:
    if emission.error_type is not None:
        return emission.error_type
    if emission.error is None:
        return None
    return emission.error.__class__.__name__


def _context_with_emission_overrides(
    context: TelemetryContextData,
    emission: TelemetryEmission,
) -> TelemetryContextData:
    return replace(
        context,
        method=context.method if emission.method is None else emission.method,
        origin=context.origin if emission.origin is None else emission.origin,
        redacted_url=context.redacted_url if emission.redacted_url is None else emission.redacted_url,
    )


def _emit_event(
    *,
    sink: TelemetryEventSink,
    event: TelemetryEvent,
    hook_error_policy: TelemetryHookErrorPolicy,
    suppress_hook_errors: bool,
) -> None:
    try:
        sink.emit(event)
    except Exception as error:  # noqa: BLE001
        if suppress_hook_errors:
            return
        if hook_error_policy == "ignore":
            return
        if hook_error_policy == "warn":
            warnings.warn(_HOOK_ERROR_MESSAGE, RuntimeWarning, stacklevel=4)
            return
        _raise_hook_error(error)


def _raise_hook_error(error: Exception) -> NoReturn:
    raise TelemetryHookError(_HOOK_ERROR_MESSAGE) from error
