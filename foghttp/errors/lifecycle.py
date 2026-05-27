__all__ = ("ClientClosedError", "LifecycleError", "UnclosedClientError")

from .base import FogHTTPError


class LifecycleError(FogHTTPError):
    """Raised when a client is used in an invalid lifecycle state."""


class ClientClosedError(LifecycleError):
    """Raised when using a closed client."""


class UnclosedClientError(ResourceWarning):
    """Warning emitted when a client is garbage collected while open."""
