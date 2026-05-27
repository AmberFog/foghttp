__all__ = ("FogHTTPError", "RequestError")


class FogHTTPError(Exception):
    """Base exception for all FogHTTP errors."""


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""
