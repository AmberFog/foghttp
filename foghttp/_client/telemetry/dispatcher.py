__all__ = ("NativeTelemetryDrain", "TelemetryDispatcher")

import threading
import time
from typing import TYPE_CHECKING

from ...request import Request
from ...telemetry import (
    TelemetryConfig,
    TelemetryEvent,
    TelemetryEventSink,
    TelemetryHookError,
    TelemetryHookErrorPolicy,
    TelemetryRequestMode,
)
from .emission import (
    NativeTelemetryContextData,
    TelemetryContextData,
    TelemetryEmission,
    TelemetryEventContext,
)
from .hook_errors import handle_hook_error
from .native import deliver_native_events
from .request_context import TelemetryRequestContext
from .url import redacted_url, url_origin


if TYPE_CHECKING:
    from foghttp import _foghttp


class _NativeDeliveryLifecycle:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_requests = 0
        self._closed = False
        self._deferred_client_error: TelemetryHookError | None = None

    def begin_request(self) -> bool:
        with self._condition:
            if self._closed:
                return False
            self._active_requests += 1
            return True

    def finish_request(self, client_error: TelemetryHookError | None) -> None:
        with self._condition:
            if client_error is not None and self._deferred_client_error is None:
                self._deferred_client_error = client_error
            self._active_requests -= 1
            self._condition.notify_all()

    def begin_close(self) -> tuple[bool, TelemetryHookError | None]:
        with self._condition:
            if self._closed:
                return False, None
            self._closed = True
            while self._active_requests:
                self._condition.wait()
            deferred_error = self._deferred_client_error
            self._deferred_client_error = None
            return True, deferred_error


class TelemetryDispatcher:
    def __init__(self, config: TelemetryConfig | None) -> None:
        self._sink = None if config is None else config.sink
        self._hook_error_policy = "raise" if config is None else config.on_hook_error
        self._lock = threading.Lock()
        self._next_event_sequence = 1
        self._next_request_id = 1
        self._native_delivery = _NativeDeliveryLifecycle()

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def request_context(self, request: Request, *, mode: TelemetryRequestMode) -> TelemetryRequestContext | None:
        if self._sink is None:
            return None

        with self._lock:
            request_id = self._next_request_id
            self._next_request_id += 1
        return TelemetryRequestContext(
            dispatcher=self,
            data=TelemetryContextData(
                request_id=request_id,
                mode=mode,
                method=request.method,
                origin=url_origin(request.url),
                redacted_url=redacted_url(request.url),
            ),
        )

    def emit(self, context: TelemetryEventContext, emission: TelemetryEmission) -> None:
        sink = self._sink
        if sink is None:
            return

        with self._lock:
            event_sequence = self._next_event_sequence
            self._next_event_sequence += 1
        event = _event_from_emission(
            context=context,
            emission=emission,
            event_sequence=event_sequence,
        )
        _emit_event(
            sink=sink,
            event=event,
            hook_error_policy=self._hook_error_policy,
            suppress_hook_errors=emission.suppress_hook_errors,
        )

    def emit_native_events(
        self,
        raw_client: "_foghttp.RawClient",
        *,
        request_id: int | None,
        suppress_hook_errors: bool,
    ) -> None:
        if self._sink is None:
            return

        if request_id is None:
            self._emit_native_close(raw_client, suppress_hook_errors=suppress_hook_errors)
            return
        self._emit_native_request(
            raw_client,
            request_id=request_id,
            suppress_hook_errors=suppress_hook_errors,
        )

    def _emit_native_request(
        self,
        raw_client: "_foghttp.RawClient",
        *,
        request_id: int,
        suppress_hook_errors: bool,
    ) -> None:
        if not self._native_delivery.begin_request():
            return
        client_error: TelemetryHookError | None = None
        try:
            request_error, client_error = deliver_native_events(
                raw_client,
                request_id=request_id,
                emit=self.emit,
                hook_error_policy=self._hook_error_policy,
                suppress_hook_errors=suppress_hook_errors,
            )
        except BaseException:
            self._native_delivery.finish_request(client_error)
            raise
        self._native_delivery.finish_request(client_error)
        if request_error is not None:
            raise request_error

    def _emit_native_close(
        self,
        raw_client: "_foghttp.RawClient",
        *,
        suppress_hook_errors: bool,
    ) -> None:
        should_deliver, deferred_client_error = self._native_delivery.begin_close()
        if not should_deliver:
            return
        request_error, client_error = deliver_native_events(
            raw_client,
            request_id=None,
            emit=self.emit,
            hook_error_policy=self._hook_error_policy,
            suppress_hook_errors=suppress_hook_errors,
        )
        client_error = deferred_client_error or client_error
        if client_error is not None and not suppress_hook_errors:
            raise client_error
        if request_error is not None:
            raise request_error


class NativeTelemetryDrain:
    def __init__(
        self,
        dispatcher: TelemetryDispatcher,
        raw_client: "_foghttp.RawClient",
        *,
        request_id: int,
    ) -> None:
        self._dispatcher = dispatcher
        self._raw_client = raw_client
        self._request_id = request_id

    def __call__(self, *, suppress_hook_errors: bool) -> None:
        self._dispatcher.emit_native_events(
            self._raw_client,
            request_id=self._request_id,
            suppress_hook_errors=suppress_hook_errors,
        )


def _event_from_emission(
    *,
    context: TelemetryEventContext,
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
    context: TelemetryEventContext,
    emission: TelemetryEmission,
) -> NativeTelemetryContextData:
    return NativeTelemetryContextData(
        request_id=context.request_id,
        mode=context.mode,
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
        handle_hook_error(
            error,
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=suppress_hook_errors,
        )
