from .lifecycle_error import LifecycleError


class ClientClosedError(LifecycleError):
    """Raised when using a closed client."""
