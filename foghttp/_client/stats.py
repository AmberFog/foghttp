__all__ = ("stats_from_raw",)

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..transport_stats import TransportStats


def stats_from_raw(
    *,
    raw: _foghttp.RawStats,
) -> TransportStats:
    return TransportStats(
        schema_version=raw.schema_version,
        snapshot_sequence=raw.snapshot_sequence,
        active_requests=raw.active_requests,
        pending_requests=raw.pending_requests,
        peak_pending_requests=raw.peak_pending_requests,
        total_requests=raw.total_requests,
        failed_requests=raw.failed_requests,
        pool_acquire_attempts=raw.pool_acquire_attempts,
        pool_acquire_immediate=raw.pool_acquire_immediate,
        pool_acquire_waited=raw.pool_acquire_waited,
        pool_acquire_timeouts=raw.pool_acquire_timeouts,
        pool_acquire_wait_time_total_ns=raw.pool_acquire_wait_time_total_ns,
        pool_acquire_wait_time_max_ns=raw.pool_acquire_wait_time_max_ns,
        pool_acquire_wait_time_last_ns=raw.pool_acquire_wait_time_last_ns,
        connection_acquire_attempts=raw.connection_acquire_attempts,
        connection_acquire_immediate=raw.connection_acquire_immediate,
        connection_acquire_waited=raw.connection_acquire_waited,
        connection_acquire_timeouts=raw.connection_acquire_timeouts,
        connection_acquire_wait_time_total_ns=raw.connection_acquire_wait_time_total_ns,
        connection_acquire_wait_time_max_ns=raw.connection_acquire_wait_time_max_ns,
        connection_acquire_wait_time_last_ns=raw.connection_acquire_wait_time_last_ns,
        response_body_reuse_eligible=raw.response_body_reuse_eligible,
        response_body_closed=raw.response_body_closed,
        response_body_aborted=raw.response_body_aborted,
        active_connections=raw.active_connections,
        idle_connections=raw.idle_connections,
        connections_opened=raw.connections_opened,
        connections_open_failed=raw.connections_open_failed,
        connections_closed=raw.connections_closed,
        connections_reused=raw.connections_reused,
        connections_aborted=raw.connections_aborted,
        buffered_response_bytes=raw.buffered_response_bytes,
        buffered_response_budget_rejections=raw.buffered_response_budget_rejections,
    )
