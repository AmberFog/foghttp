__all__ = (
    "ClientClosedError",
    "ConnectTimeout",
    "FogHTTPError",
    "HTTPStatusError",
    "LifecycleError",
    "PoolTimeout",
    "ReadTimeout",
    "RequestError",
    "ResponseBodyBudgetExceededError",
    "ResponseBodyTooLargeError",
    "ResponseError",
    "TimeoutError",
    "UnclosedClientError",
)

from ..timeout_diagnostics import TimeoutDiagnostic, TimeoutPhase


class FogHTTPError(Exception):
    """Base exception for all FogHTTP errors."""


class RequestError(FogHTTPError):
    """Raised when a request cannot be completed."""


class TimeoutError(RequestError):
    """Raised when a timeout expires."""

    def __init__(
        self,
        message: str = "",
        *,
        diagnostic: TimeoutDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic

    @property
    def phase(self) -> TimeoutPhase | None:
        return None if self.diagnostic is None else self.diagnostic.phase

    @property
    def elapsed(self) -> float | None:
        return None if self.diagnostic is None else self.diagnostic.elapsed

    @property
    def timeout(self) -> float | None:
        return None if self.diagnostic is None else self.diagnostic.timeout

    @property
    def origin(self) -> str | None:
        return None if self.diagnostic is None else self.diagnostic.origin

    @property
    def redirect_hop(self) -> int | None:
        return None if self.diagnostic is None else self.diagnostic.redirect_hop


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


class ResponseBodyBudgetExceededError(ResponseError):
    """Raised when concurrent buffered responses exceed the aggregate budget."""


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
