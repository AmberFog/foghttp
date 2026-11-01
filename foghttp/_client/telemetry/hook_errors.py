__all__ = ("DeferredHookError", "deferred_hook_error", "handle_hook_error", "report_deferred_hook_error")

from typing import NoReturn, TypeAlias
import warnings

from ...telemetry import TelemetryHookError, TelemetryHookErrorPolicy


DeferredHookError: TypeAlias = TelemetryHookError | RuntimeWarning


_HOOK_ERROR_MESSAGE = "telemetry event sink failed"


def handle_hook_error(
    error: Exception,
    *,
    hook_error_policy: TelemetryHookErrorPolicy,
    suppress_hook_errors: bool,
) -> None:
    if suppress_hook_errors or hook_error_policy == "ignore":
        return
    if hook_error_policy == "warn":
        warnings.warn(_HOOK_ERROR_MESSAGE, RuntimeWarning, stacklevel=5)
        return
    _raise_hook_error(error)


def deferred_hook_error(
    error: Exception,
    *,
    hook_error_policy: TelemetryHookErrorPolicy,
    suppress_hook_errors: bool,
    defer_warning_errors: bool = False,
) -> DeferredHookError | None:
    try:
        handle_hook_error(
            error,
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=suppress_hook_errors,
        )
    except TelemetryHookError as hook_error:
        return hook_error
    except RuntimeWarning as warning_error:
        if defer_warning_errors:
            return warning_error
        raise
    return None


def report_deferred_hook_error(
    error: DeferredHookError,
    *,
    suppress_hook_errors: bool,
) -> None:
    if suppress_hook_errors:
        return
    if isinstance(error, RuntimeWarning):
        if error.__cause__ is None:
            error.__cause__ = error.__context__
        warnings.warn(error, stacklevel=6)
    else:
        raise error


def _raise_hook_error(error: Exception) -> NoReturn:
    raise TelemetryHookError(_HOOK_ERROR_MESSAGE) from error
