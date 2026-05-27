__all__ = (
    "HTTPStatusError",
    "ResponseBodyBudgetExceededError",
    "ResponseBodyTooLargeError",
    "ResponseError",
)

from .base import FogHTTPError


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
