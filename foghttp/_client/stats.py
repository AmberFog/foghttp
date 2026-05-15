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
        total_requests=raw.total_requests,
        failed_requests=raw.failed_requests,
        pool_acquire_timeouts=raw.pool_acquire_timeouts,
    )
