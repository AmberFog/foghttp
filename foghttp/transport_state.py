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
    connection_acquire_attempts: int
    connection_acquire_immediate: int
    connection_acquire_waited: int
    connection_acquire_timeouts: int
    connection_acquire_wait_time_total_ns: int
    connection_acquire_wait_time_max_ns: int
    connection_acquire_wait_time_last_ns: int
    response_body_reuse_eligible: int
    response_body_closed: int
    response_body_aborted: int
    active_connections: int
    idle_connections: int
    connections_opened: int
    connections_open_failed: int
    connections_closed: int
    connections_reused: int
    connections_aborted: int
    idle_timeout_evictions: int
    last_activity_at_ns: int


class TransportState(TypedDict):
    schema_version: int
    snapshot_sequence: int
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
    connection_acquire_attempts: int
    connection_acquire_immediate: int
    connection_acquire_waited: int
    connection_acquire_timeouts: int
    connection_acquire_wait_time_total_ns: int
    connection_acquire_wait_time_max_ns: int
    connection_acquire_wait_time_last_ns: int
    response_body_reuse_eligible: int
    response_body_closed: int
    response_body_aborted: int
    active_connections: int
    idle_connections: int
    connections_opened: int
    connections_open_failed: int
    connections_closed: int
    connections_reused: int
    connections_aborted: int
    idle_timeout_evictions: int
    buffered_response_bytes: int
    buffered_response_budget_rejections: int
    origins: dict[str, OriginPressureState]
