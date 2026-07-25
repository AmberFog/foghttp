__all__ = ("deferred_hook_error", "handle_hook_error")

from typing import NoReturn
import warnings

from ...telemetry import TelemetryHookError, TelemetryHookErrorPolicy


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
) -> TelemetryHookError | None:
    try:
        handle_hook_error(
            error,
            hook_error_policy=hook_error_policy,
            suppress_hook_errors=suppress_hook_errors,
        )
    except TelemetryHookError as hook_error:
        return hook_error
    return None


def _raise_hook_error(error: Exception) -> NoReturn:
    raise TelemetryHookError(_HOOK_ERROR_MESSAGE) from error
