__all__ = ("FogHTTPError", "NetworkError", "RequestError")


class FogHTTPError(Exception):
    """Base exception for all FogHTTP errors."""


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""


class NetworkError(RequestError):
    """Raised when the transport fails before response headers are available."""
