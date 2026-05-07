__all__ = ("stats_from_raw",)

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..pool_stats import PoolStats


def stats_from_raw(
    *,
    raw: _foghttp.RawStats,
    pending_acquires: int,
    pool_timeouts: int,
) -> PoolStats:
    return PoolStats(
        active_connections=raw.active_connections,
        idle_connections=raw.idle_connections,
        pending_acquires=pending_acquires,
        total_requests=raw.total_requests,
        failed_requests=raw.failed_requests,
        reused_connections=raw.reused_connections,
        opened_connections=raw.opened_connections,
        closed_connections=raw.closed_connections,
        pool_timeouts=raw.pool_timeouts + pool_timeouts,
    )
