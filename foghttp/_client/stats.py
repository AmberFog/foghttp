__all__ = ("stats_from_raw",)

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..transport_stats import TransportStats


def stats_from_raw(
    *,
    raw: _foghttp.RawStats,
) -> TransportStats:
    return TransportStats(
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
        buffered_response_bytes=raw.buffered_response_bytes,
        buffered_response_budget_rejections=raw.buffered_response_budget_rejections,
    )
