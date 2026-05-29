from types import SimpleNamespace

import foghttp
from foghttp._client.stats import stats_from_raw


def test_stats_from_raw_maps_unique_transport_stat_fields() -> None:
    raw_values = {
        field_name: field_index
        for field_index, field_name in enumerate(
            foghttp.TransportStats.__dataclass_fields__,
            start=1,
        )
    }
    raw_stats = SimpleNamespace(**raw_values)

    stats = stats_from_raw(raw=raw_stats)

    assert stats == foghttp.TransportStats(**raw_values)
    assert stats.schema_version == raw_values["schema_version"]
    assert stats.snapshot_sequence == raw_values["snapshot_sequence"]


def test_transport_stats_equality_ignores_snapshot_sequence_only() -> None:
    first = foghttp.TransportStats(total_requests=1, snapshot_sequence=1)
    second = foghttp.TransportStats(total_requests=1, snapshot_sequence=2)
    different_schema = foghttp.TransportStats(total_requests=1, schema_version=2)
    different_metrics = foghttp.TransportStats(total_requests=2, snapshot_sequence=1)

    assert first == second
    assert first != different_schema
    assert first != different_metrics
