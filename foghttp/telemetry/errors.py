__all__ = ("TelemetryHookError",)

from ..errors.base import FogHTTPError


class TelemetryHookError(FogHTTPError):
    """Raised when a telemetry event sink fails and the policy is 'raise'."""
