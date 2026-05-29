from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import foghttp
from foghttp.status_codes.success import OK


if TYPE_CHECKING:
    from collections.abc import Callable


CONCURRENT_SNAPSHOT_ROUNDS = 10
SYNTHETIC_SNAPSHOT_SEQUENCE = 0
TELEMETRY_SCHEMA_VERSION = 1

Snapshot = foghttp.TransportStats | foghttp.TransportState | foghttp.PoolDiagnostics


def test_sync_diagnostic_snapshots_before_transport_are_synthetic() -> None:
    with foghttp.Client() as client:
        stats = client.stats()
        state = client.dump_transport_state()
        diagnostics = client.dump_pool_diagnostics()

    assert stats.schema_version == TELEMETRY_SCHEMA_VERSION
    assert stats.snapshot_sequence == SYNTHETIC_SNAPSHOT_SEQUENCE
    assert state["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert state["snapshot_sequence"] == SYNTHETIC_SNAPSHOT_SEQUENCE
    assert diagnostics["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert diagnostics["snapshot_sequence"] == SYNTHETIC_SNAPSHOT_SEQUENCE


def test_sync_diagnostic_snapshot_sequence_is_monotonic(
    sync_resource_http_server: str,
) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_resource_http_server)
        stats = client.stats()
        state = client.dump_transport_state()
        diagnostics = client.dump_pool_diagnostics()
        next_stats = client.stats()

    assert response.status_code == OK
    assert stats.schema_version == TELEMETRY_SCHEMA_VERSION
    assert state["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert diagnostics["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert next_stats.schema_version == TELEMETRY_SCHEMA_VERSION
    assert (
        SYNTHETIC_SNAPSHOT_SEQUENCE
        < stats.snapshot_sequence
        < state["snapshot_sequence"]
        < diagnostics["snapshot_sequence"]
        < next_stats.snapshot_sequence
    )


def test_sync_telemetry_snapshot_sequence_is_unique_for_concurrent_observers(
    sync_resource_http_server: str,
) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_resource_http_server)
        snapshot_readers: tuple[Callable[[], Snapshot], ...] = (
            client.stats,
            client.dump_transport_state,
            client.dump_pool_diagnostics,
        )
        with ThreadPoolExecutor(
            max_workers=len(snapshot_readers) * CONCURRENT_SNAPSHOT_ROUNDS,
        ) as executor:
            futures = [
                executor.submit(snapshot_reader)
                for _round_index in range(CONCURRENT_SNAPSHOT_ROUNDS)
                for snapshot_reader in snapshot_readers
            ]
            snapshots = [future.result(timeout=1.0) for future in futures]

    sequences = [_snapshot_sequence(snapshot) for snapshot in snapshots]

    assert response.status_code == OK
    assert min(sequences) > SYNTHETIC_SNAPSHOT_SEQUENCE
    assert len(sequences) == len(set(sequences))


async def test_async_diagnostic_snapshot_sequence_is_monotonic(
    resource_http_server: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(resource_http_server)
        stats = client.stats()
        state = client.dump_transport_state()
        diagnostics = client.dump_pool_diagnostics()
        next_stats = client.stats()

    assert response.status_code == OK
    assert stats.schema_version == TELEMETRY_SCHEMA_VERSION
    assert state["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert diagnostics["schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert next_stats.schema_version == TELEMETRY_SCHEMA_VERSION
    assert (
        SYNTHETIC_SNAPSHOT_SEQUENCE
        < stats.snapshot_sequence
        < state["snapshot_sequence"]
        < diagnostics["snapshot_sequence"]
        < next_stats.snapshot_sequence
    )


def _snapshot_sequence(snapshot: Snapshot) -> int:
    if isinstance(snapshot, foghttp.TransportStats):
        return snapshot.snapshot_sequence
    return snapshot["snapshot_sequence"]
