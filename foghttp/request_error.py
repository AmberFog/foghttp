from .fog_http_error import FogHTTPError


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""
