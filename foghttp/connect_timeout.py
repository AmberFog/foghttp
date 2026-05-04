from .timeout_error import TimeoutError


class ConnectTimeout(TimeoutError):
    """Raised when connecting to the remote peer times out."""
