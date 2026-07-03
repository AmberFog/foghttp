from concurrent.futures import (
    ThreadPoolExecutor,
)
import threading

from faker import Faker
import pytest

import foghttp
from foghttp._telemetry import TELEMETRY_SNAPSHOT_SCHEMA_VERSION

from .constants import SHORT_LIVED_CLIENT_COUNT
from .helpers import (
    CloseTrackingRawClient,
    RawClientFactory,
)


def test_sync_client_creation_is_lazy(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
) -> None:
    client = sync_client_factory()

    client.close()

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


def test_sync_stats_before_first_request_do_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
) -> None:
    client = sync_client_factory()

    stats = client.stats()
    client.close()

    assert stats == foghttp.TransportStats()
    assert raw_client_factory.calls == 0


def test_sync_closed_client_rejects_stats(
    sync_client_factory: type[foghttp.Client],
) -> None:
    client = sync_client_factory()
    client.close()

    with pytest.raises(foghttp.ClientClosedError, match="FogHTTP client is closed"):
        client.stats()


def test_sync_dump_transport_state_before_first_request_do_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
) -> None:
    client = sync_client_factory()

    state = client.dump_transport_state()
    client.close()

    assert state == {
        "active_connections": 0,
        "active_requests": 0,
        "buffered_response_bytes": 0,
        "buffered_response_budget_rejections": 0,
        "connection_acquire_attempts": 0,
        "connection_acquire_immediate": 0,
        "connection_acquire_timeouts": 0,
        "connection_acquire_wait_time_last_ns": 0,
        "connection_acquire_wait_time_max_ns": 0,
        "connection_acquire_wait_time_total_ns": 0,
        "connection_acquire_waited": 0,
        "connections_aborted": 0,
        "connections_closed": 0,
        "connections_open_failed": 0,
        "connections_opened": 0,
        "connections_reused": 0,
        "idle_connections": 0,
        "peak_pending_requests": 0,
        "pending_requests": 0,
        "pool_acquire_attempts": 0,
        "pool_acquire_immediate": 0,
        "pool_acquire_timeouts": 0,
        "pool_acquire_wait_time_last_ns": 0,
        "pool_acquire_wait_time_max_ns": 0,
        "pool_acquire_wait_time_total_ns": 0,
        "pool_acquire_waited": 0,
        "response_body_aborted": 0,
        "response_body_closed": 0,
        "response_body_reuse_eligible": 0,
        "schema_version": TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_sequence": 0,
        "origins": {},
    }
    assert raw_client_factory.calls == 0


def test_sync_close_closes_opened_raw_client_once(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    sync_noop_transport: None,
    faker: Faker,
) -> None:
    client = sync_client_factory()

    client.get(faker.url())
    client.close()
    client.close()

    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1


def test_sync_context_manager_without_request_does_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
) -> None:
    with sync_client_factory():
        pass

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


@pytest.mark.parametrize("client_options", [{}, {"runtime": "dedicated"}])
def test_sync_short_lived_clients_without_requests_do_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    client_options: dict[str, object],
) -> None:
    for _index in range(SHORT_LIVED_CLIENT_COUNT):
        client = sync_client_factory(**client_options)
        client.close()

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


def test_sync_reuses_lazy_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
    sync_noop_transport: None,
    faker: Faker,
) -> None:
    urls = [faker.url(), faker.url()]

    with sync_client_factory() as client:
        client.get(urls[0])
        client.get(urls[1])

    assert raw_client_factory.calls == 1


def test_sync_concurrent_first_requests_share_lazy_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
    sync_noop_transport: None,
    faker: Faker,
) -> None:
    raw_client_factory.delay = 0.01
    workers = 8
    barrier = threading.Barrier(workers)
    urls = [faker.url() for _index in range(workers)]

    with sync_client_factory() as client:

        def send_request(index: int) -> None:
            barrier.wait()
            client.get(urls[index])

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(send_request, index) for index in range(workers)]
            for future in futures:
                future.result()

    assert raw_client_factory.calls == 1


def test_sync_context_manager_closes_opened_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    sync_noop_transport: None,
    faker: Faker,
) -> None:
    with sync_client_factory() as client:
        client.get(faker.url())

    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1
