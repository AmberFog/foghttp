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
