from dataclasses import fields
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
    "connection_acquire_attempts": 13,
    "connection_acquire_immediate": 14,
    "connection_acquire_waited": 15,
    "connection_acquire_timeouts": 16,
    "connection_acquire_wait_time_total_ns": 17,
    "connection_acquire_wait_time_max_ns": 18,
    "connection_acquire_wait_time_last_ns": 19,
    "response_body_reuse_eligible": 20,
    "response_body_closed": 21,
    "response_body_aborted": 22,
    "active_connections": 23,
    "idle_connections": 24,
    "connections_opened": 25,
    "connections_open_failed": 26,
    "connections_closed": 27,
    "connections_reused": 28,
    "connections_aborted": 29,
    "idle_timeout_evictions": 30,
    "buffered_response_bytes": 31,
    "buffered_response_budget_rejections": 32,
    "schema_version": 33,
    "snapshot_sequence": 34,
}


def test_raw_stats_values_cover_transport_stats_contract() -> None:
    transport_stat_fields = {stat_field.name for stat_field in fields(foghttp.TransportStats)}

    assert set(RAW_STATS_VALUES) == transport_stat_fields


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
