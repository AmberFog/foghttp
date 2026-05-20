__all__ = ("OriginPressureState", "TransportState")

from typing import TypedDict


class OriginPressureState(TypedDict):
    active_requests: int
    pending_requests: int
    peak_pending_requests: int
    pool_acquire_attempts: int
    pool_acquire_immediate: int
    pool_acquire_waited: int
    pool_acquire_timeouts: int
    pool_acquire_wait_time_total_ns: int
    pool_acquire_wait_time_max_ns: int
    pool_acquire_wait_time_last_ns: int


class TransportState(TypedDict):
    active_requests: int
    pending_requests: int
    peak_pending_requests: int
    pool_acquire_attempts: int
    pool_acquire_immediate: int
    pool_acquire_waited: int
    pool_acquire_timeouts: int
    pool_acquire_wait_time_total_ns: int
    pool_acquire_wait_time_max_ns: int
    pool_acquire_wait_time_last_ns: int
    buffered_response_bytes: int
    buffered_response_budget_rejections: int
    origins: dict[str, OriginPressureState]
