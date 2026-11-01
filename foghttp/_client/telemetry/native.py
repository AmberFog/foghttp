__all__ = (
    "current_native_request_id",
    "deliver_native_events",
    "native_emission",
    "native_request_id_scope",
)

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from ...telemetry import (
    TelemetryEventType,
    TelemetryHookError,
    TelemetryHookErrorPolicy,
    TelemetryRequestMode,
    TelemetryRequestOutcome,
)
from .emission import NativeTelemetryContextData, TelemetryEmission, TelemetryEventContext
from .hook_errors import DeferredHookError, deferred_hook_error


if TYPE_CHECKING:
    from foghttp import _foghttp


_NATIVE_REQUEST_ID: ContextVar[int | None] = ContextVar(
    "foghttp_native_telemetry_request_id",
    default=None,
)
_NATIVE_EVENTS_DROPPED_MESSAGE = "native telemetry event buffer overflowed"


@contextmanager
def native_request_id_scope(request_id: int) -> Iterator[None]:
    token = _NATIVE_REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _NATIVE_REQUEST_ID.reset(token)


def current_native_request_id() -> int | None:
    return _NATIVE_REQUEST_ID.get()


def deliver_native_events(
    raw_client: "_foghttp.RawClient",
    *,
    request_id: int | None,
    emit: Callable[[TelemetryEventContext, TelemetryEmission], None],
    hook_error_policy: TelemetryHookErrorPolicy,
    suppress_hook_errors: bool,
) -> tuple[DeferredHookError | None, DeferredHookError | None]:
    raw_events, dropped_events = raw_client.drain_telemetry_events(request_id)
    request_error, client_error = _deliver_native_records(
        raw_events,
        emit=emit,
        hook_error_policy=hook_error_policy,
        request_id=request_id,
        suppress_hook_errors=suppress_hook_errors,
    )
    if dropped_events:
        overflow_error = deferred_hook_error(
            RuntimeError(_NATIVE_EVENTS_DROPPED_MESSAGE),
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=suppress_hook_errors or client_error is not None,
        )
        client_error = client_error or overflow_error
    return request_error, client_error


def _deliver_native_records(
    raw_events: list["_foghttp.RawTelemetryEvent"],
    *,
    emit: Callable[[TelemetryEventContext, TelemetryEmission], None],
    hook_error_policy: TelemetryHookErrorPolicy,
    request_id: int | None,
    suppress_hook_errors: bool,
) -> tuple[DeferredHookError | None, DeferredHookError | None]:
    request_error: DeferredHookError | None = None
    client_error: DeferredHookError | None = None
    for raw in raw_events:
        if raw.request_id is not None:
            event_error = _deliver_native_record(
                raw,
                emit=emit,
                hook_error_policy=hook_error_policy,
                suppress_hook_errors=request_error is not None or suppress_hook_errors or request_id is None,
            )
            request_error = request_error or event_error
            continue
        event_error = _deliver_native_record(
            raw,
            emit=emit,
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=client_error is not None or (suppress_hook_errors and request_id is None),
            defer_warning_errors=suppress_hook_errors and request_id is not None,
        )
        client_error = client_error or event_error
    return request_error, client_error


def _deliver_native_record(
    raw: "_foghttp.RawTelemetryEvent",
    *,
    emit: Callable[[TelemetryEventContext, TelemetryEmission], None],
    hook_error_policy: TelemetryHookErrorPolicy,
    suppress_hook_errors: bool,
    defer_warning_errors: bool = False,
) -> DeferredHookError | None:
    try:
        context, emission = native_emission(
            raw,
            suppress_hook_errors=suppress_hook_errors,
        )
        emit(context, emission)
    except TelemetryHookError as error:
        return error
    except RuntimeWarning as error:
        if defer_warning_errors:
            return error
        raise
    except Exception as error:  # noqa: BLE001
        return deferred_hook_error(
            error,
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=suppress_hook_errors,
            defer_warning_errors=defer_warning_errors,
        )
    return None


def native_emission(
    raw: "_foghttp.RawTelemetryEvent",
    *,
    suppress_hook_errors: bool,
) -> tuple[NativeTelemetryContextData, TelemetryEmission]:
    origin = raw.origin
    context = NativeTelemetryContextData(
        request_id=raw.request_id,
        mode=None if raw.mode is None else TelemetryRequestMode(raw.mode),
        method=raw.method,
        origin=origin,
        redacted_url=origin,
    )
    emission = TelemetryEmission(
        event_type=TelemetryEventType(raw.event_type),
        elapsed_ns=raw.elapsed_ns,
        redirect_hop=raw.redirect_hop,
        outcome=None if raw.outcome is None else TelemetryRequestOutcome(raw.outcome),
        error_type=raw.error_type,
        suppress_hook_errors=suppress_hook_errors,
    )
    return context, emission
