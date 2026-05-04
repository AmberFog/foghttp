from .request_error import RequestError


class TimeoutError(RequestError):
    """Raised when a timeout expires."""
