__all__ = ("ConnectTimeout", "PoolTimeout", "ReadTimeout", "TimeoutError")

from ..timeout_diagnostics import TimeoutDiagnostic, TimeoutPhase
from .base import RequestError


class TimeoutError(RequestError):
    """Raised when a timeout expires."""

    def __init__(
        self,
        message: str = "",
        *,
        diagnostic: TimeoutDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic

    @property
    def phase(self) -> TimeoutPhase | None:
        return None if self.diagnostic is None else self.diagnostic.phase

    @property
    def elapsed(self) -> float | None:
        return None if self.diagnostic is None else self.diagnostic.elapsed

    @property
    def timeout(self) -> float | None:
        return None if self.diagnostic is None else self.diagnostic.timeout

    @property
    def origin(self) -> str | None:
        return None if self.diagnostic is None else self.diagnostic.origin

    @property
    def redirect_hop(self) -> int | None:
        return None if self.diagnostic is None else self.diagnostic.redirect_hop


class ConnectTimeout(TimeoutError):
    """Raised when connecting to the remote peer times out."""


class ReadTimeout(TimeoutError):
    """Raised when reading a response times out."""


class PoolTimeout(TimeoutError):
    """Raised when waiting for a pooled connection times out."""
