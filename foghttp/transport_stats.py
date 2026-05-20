__all__ = ("TransportStats",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransportStats:
    active_requests: int = 0
    pending_requests: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    pool_acquire_timeouts: int = 0
    buffered_response_bytes: int = 0
    buffered_response_budget_rejections: int = 0
