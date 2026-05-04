from .response_error import ResponseError


class HTTPStatusError(ResponseError):
    """Raised by Response.raise_for_status for 4xx and 5xx responses."""

    def __init__(self, message: str, *, response: object) -> None:
        super().__init__(message)
        self.response = response
