from types import SimpleNamespace

import foghttp
from foghttp._client.stats import stats_from_raw


def test_stats_from_raw_maps_unique_transport_stat_fields() -> None:
    raw_stats = SimpleNamespace(
        active_requests=1,
        pending_requests=2,
        peak_pending_requests=3,
        total_requests=4,
        failed_requests=5,
        pool_acquire_attempts=6,
        pool_acquire_immediate=7,
        pool_acquire_waited=8,
        pool_acquire_timeouts=9,
        pool_acquire_wait_time_total_ns=10,
        pool_acquire_wait_time_max_ns=11,
        pool_acquire_wait_time_last_ns=12,
        response_body_reuse_eligible=13,
        response_body_closed=14,
        response_body_aborted=15,
        buffered_response_bytes=16,
        buffered_response_budget_rejections=17,
    )

    stats = stats_from_raw(raw=raw_stats)

    assert stats == foghttp.TransportStats(
        active_requests=1,
        pending_requests=2,
        peak_pending_requests=3,
        total_requests=4,
        failed_requests=5,
        pool_acquire_attempts=6,
        pool_acquire_immediate=7,
        pool_acquire_waited=8,
        pool_acquire_timeouts=9,
        pool_acquire_wait_time_total_ns=10,
        pool_acquire_wait_time_max_ns=11,
        pool_acquire_wait_time_last_ns=12,
        response_body_reuse_eligible=13,
        response_body_closed=14,
        response_body_aborted=15,
        buffered_response_bytes=16,
        buffered_response_budget_rejections=17,
    )
