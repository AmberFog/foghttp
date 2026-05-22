__all__ = ("TransportStats",)

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransportStats:
    active_requests: int = 0
    pending_requests: int = 0
    peak_pending_requests: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    pool_acquire_attempts: int = 0
    pool_acquire_immediate: int = 0
    pool_acquire_waited: int = 0
    pool_acquire_timeouts: int = 0
    pool_acquire_wait_time_total_ns: int = 0
    pool_acquire_wait_time_max_ns: int = 0
    pool_acquire_wait_time_last_ns: int = 0
    response_body_reuse_eligible: int = 0
    response_body_closed: int = 0
    response_body_aborted: int = 0
    buffered_response_bytes: int = 0
    buffered_response_budget_rejections: int = 0
