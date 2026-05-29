from types import SimpleNamespace

import foghttp
from foghttp._client.stats import stats_from_raw


RAW_STATS_VALUES = {
    "active_requests": 1,
    "pending_requests": 2,
    "peak_pending_requests": 3,
    "total_requests": 4,
    "failed_requests": 5,
    "pool_acquire_attempts": 6,
    "pool_acquire_immediate": 7,
    "pool_acquire_waited": 8,
    "pool_acquire_timeouts": 9,
    "pool_acquire_wait_time_total_ns": 10,
    "pool_acquire_wait_time_max_ns": 11,
    "pool_acquire_wait_time_last_ns": 12,
    "response_body_reuse_eligible": 13,
    "response_body_closed": 14,
    "response_body_aborted": 15,
    "active_connections": 16,
    "idle_connections": 17,
    "connections_opened": 18,
    "connections_open_failed": 19,
    "connections_closed": 20,
    "connections_reused": 21,
    "connections_aborted": 22,
    "buffered_response_bytes": 23,
    "buffered_response_budget_rejections": 24,
    "schema_version": 25,
    "snapshot_sequence": 26,
}


def test_stats_from_raw_maps_unique_transport_stat_fields() -> None:
    raw_stats = SimpleNamespace(**RAW_STATS_VALUES)

    stats = stats_from_raw(raw=raw_stats)

    assert stats == foghttp.TransportStats(**RAW_STATS_VALUES)
    assert stats.schema_version == RAW_STATS_VALUES["schema_version"]
    assert stats.snapshot_sequence == RAW_STATS_VALUES["snapshot_sequence"]


def test_transport_stats_equality_includes_snapshot_metadata() -> None:
    first = foghttp.TransportStats(total_requests=1, snapshot_sequence=1)
    second = foghttp.TransportStats(total_requests=1, snapshot_sequence=2)
    different_schema = foghttp.TransportStats(total_requests=1, schema_version=2)
    different_metrics = foghttp.TransportStats(total_requests=2, snapshot_sequence=1)

    assert first != second
    assert first != different_schema
    assert first != different_metrics
