__all__ = (
    "OriginPoolDiagnostics",
    "PoolBlockingReason",
    "PoolDiagnostics",
)

from typing import Literal, TypedDict


PoolBlockingReason = Literal[
    "none",
    "global_active_requests",
    "per_origin_active_requests",
    "mixed",
]


class OriginPoolDiagnostics(TypedDict):
    active_requests: int
    pending_requests: int
    pool_acquire_timeouts: int
    oldest_pending_request_wait_ns: int
    blocked_by: PoolBlockingReason
    last_activity_at_ns: int


class PoolDiagnostics(TypedDict):
    schema_version: int
    snapshot_sequence: int
    active_requests: int
    pending_requests: int
    pool_acquire_timeouts: int
    max_active_requests: int
    max_active_requests_per_origin: int | None
    max_pending_requests: int
    pending_queue_full: bool
    oldest_pending_request_wait_ns: int
    blocked_by: PoolBlockingReason
    origins: dict[str, OriginPoolDiagnostics]
