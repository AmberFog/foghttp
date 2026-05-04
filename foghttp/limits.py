from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Limits:
    max_connections: int = 100
    max_connections_per_host: int = 20
    max_pending_acquires: int = 1000
    idle_timeout: float = 30.0
    keepalive: bool = True
