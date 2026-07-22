__all__ = (
    "HTTPStatusError",
    "ResponseBodyBudgetExceededError",
    "ResponseBodyTooLargeError",
    "ResponseError",
)

from typing import TYPE_CHECKING

from .base import FogHTTPError


if TYPE_CHECKING:
    from ..retry_trace import RetryTrace


class ResponseError(FogHTTPError):
    """Raised for response handling errors."""


class ResponseBodyTooLargeError(ResponseError):
    """Raised when a buffered response body exceeds the configured limit."""


class ResponseBodyBudgetExceededError(ResponseError):
    """Raised when concurrent buffered responses exceed the aggregate budget."""


class HTTPStatusError(ResponseError):
    """Raised by Response.raise_for_status for 4xx and 5xx responses."""

    def __init__(
        self,
        message: str,
        *,
        response: object,
        retry_trace: "RetryTrace | None" = None,
    ) -> None:
        super().__init__(message)
        self.response = response
        self._retry_trace = retry_trace
