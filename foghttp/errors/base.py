__all__ = ("FogHTTPError", "NetworkError", "RequestError")

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from ..retry_trace import RetryTrace


class FogHTTPError(Exception):
    """Base exception for all FogHTTP errors."""

    _retry_trace: "RetryTrace | None" = None

    @property
    def retry_trace(self) -> "RetryTrace | None":
        return self._retry_trace


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""


class NetworkError(RequestError):
    """Raised when the transport fails before response headers are available."""
