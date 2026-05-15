__all__ = ("Limits",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limits:
    max_active_requests: int = 100
    max_active_requests_per_origin: int | None = None
    max_pending_requests: int = 1000
    max_idle_connections_per_host: int = 20
    idle_timeout: float = 30.0
    keepalive: bool = True
