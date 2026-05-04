from .timeout_error import TimeoutError


class ReadTimeout(TimeoutError):
    """Raised when reading a response times out."""
