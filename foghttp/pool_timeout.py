from .timeout_error import TimeoutError


class PoolTimeout(TimeoutError):
    """Raised when waiting for a pooled connection times out."""
