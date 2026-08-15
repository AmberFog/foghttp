__all__ = ("ConfigurationError",)

from .base import FogHTTPError


class ConfigurationError(FogHTTPError, ValueError):
    """Raised when lazy client transport setup fails."""
