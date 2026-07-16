import pytest

import foghttp
from tests.support import transport_stats


EXPECTED_STATS_CALLS = 2


class StatsSequence:
    def __init__(self, snapshots: list[foghttp.TransportStats]) -> None:
        self._snapshots = iter(snapshots)
        self.calls = 0

    def stats(self) -> foghttp.TransportStats:
        self.calls += 1
        return next(self._snapshots)


def test_sync_waiter_checks_stats_after_last_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StatsSequence(_pending_then_completed_stats())
    monkeypatch.setattr(transport_stats, "MAX_STATS_POLLS", 1)
    monkeypatch.setattr(transport_stats, "STATS_POLL_INTERVAL", 0)

    transport_stats.wait_for_sync_transport_stats(
        client,
        lambda stats: stats.total_requests == 1,
        message="expected final snapshot to be checked",
    )

    assert client.calls == EXPECTED_STATS_CALLS


async def test_async_waiter_checks_stats_after_last_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    client = StatsSequence(_pending_then_completed_stats())
    monkeypatch.setattr(transport_stats, "MAX_STATS_POLLS", 1)
    monkeypatch.setattr(transport_stats, "STATS_POLL_INTERVAL", 0)

    await transport_stats.wait_for_async_transport_stats(
        client,
        lambda stats: stats.total_requests == 1,
        message="expected final snapshot to be checked",
    )

    assert client.calls == EXPECTED_STATS_CALLS


def _pending_then_completed_stats() -> list[foghttp.TransportStats]:
    return [
        foghttp.TransportStats(),
        foghttp.TransportStats(total_requests=1),
    ]
