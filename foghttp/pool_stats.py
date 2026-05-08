from dataclasses import dataclass


__all__ = ("PoolStats",)


@dataclass(frozen=True, slots=True)
class PoolStats:
    active_connections: int = 0
    idle_connections: int = 0
    pending_acquires: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    reused_connections: int = 0
    opened_connections: int = 0
    closed_connections: int = 0
    pool_timeouts: int = 0
