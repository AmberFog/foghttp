__all__ = (
    "ClientClosedError",
    "ConnectTimeout",
    "FogHTTPError",
    "HTTPStatusError",
    "LifecycleError",
    "PoolTimeout",
    "ReadTimeout",
    "RequestError",
    "ResponseBodyTooLargeError",
    "ResponseError",
    "TimeoutError",
    "UnclosedClientError",
)


class FogHTTPError(Exception):
    """Base exception for all FogHTTP errors."""


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""


class TimeoutError(RequestError):
    """Raised when a timeout expires."""


class ConnectTimeout(TimeoutError):
    """Raised when connecting to the remote peer times out."""


class ReadTimeout(TimeoutError):
    """Raised when reading a response times out."""


class PoolTimeout(TimeoutError):
    """Raised when waiting for a pooled connection times out."""


class ResponseError(FogHTTPError):
    """Raised for response handling errors."""


class ResponseBodyTooLargeError(ResponseError):
    """Raised when a buffered response body exceeds the configured limit."""


class HTTPStatusError(ResponseError):
    """Raised by Response.raise_for_status for 4xx and 5xx responses."""

    def __init__(self, message: str, *, response: object) -> None:
        super().__init__(message)
        self.response = response


class LifecycleError(FogHTTPError):
    """Raised when a client is used in an invalid lifecycle state."""


class ClientClosedError(LifecycleError):
    """Raised when using a closed client."""


class UnclosedClientError(ResourceWarning):
    """Warning emitted when a client is garbage collected while open."""
