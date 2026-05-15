from types import SimpleNamespace

import foghttp
from foghttp._client.stats import stats_from_raw


def test_stats_from_raw_maps_unique_transport_stat_fields() -> None:
    raw_stats = SimpleNamespace(
        active_requests=1,
        pending_requests=2,
        total_requests=3,
        failed_requests=4,
        pool_acquire_timeouts=5,
    )

    stats = stats_from_raw(raw=raw_stats)

    assert stats == foghttp.TransportStats(
        active_requests=1,
        pending_requests=2,
        total_requests=3,
        failed_requests=4,
        pool_acquire_timeouts=5,
    )
