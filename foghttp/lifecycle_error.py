from .fog_http_error import FogHTTPError


class LifecycleError(FogHTTPError):
    """Raised when a client is used in an invalid lifecycle state."""
