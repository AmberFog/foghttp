import asyncio

from faker import Faker
import pytest

import foghttp
from foghttp._telemetry import TELEMETRY_SNAPSHOT_SCHEMA_VERSION

from .constants import SHORT_LIVED_CLIENT_COUNT
from .helpers import CloseTrackingRawClient, RawClientFactory


async def test_async_client_creation_is_lazy(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    await client.aclose()

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


async def test_async_stats_before_first_request_do_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    stats = client.stats()
    await client.aclose()

    assert stats == foghttp.TransportStats()
    assert raw_client_factory.calls == 0


async def test_async_lifecycle_debug_snapshot_without_debug_does_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    snapshot = client.dump_lifecycle_debug()
    client.assert_no_lifecycle_leaks()
    await client.aclose()

    assert snapshot == foghttp.AsyncLifecycleDebugSnapshot(
        enabled=False,
        strict=False,
        closed=False,
        active_requests=(),
        transport_active_requests=0,
        transport_pending_requests=0,
        pool_acquire_timeouts=0,
    )
    assert raw_client_factory.calls == 0


async def test_async_closed_client_rejects_stats(
    async_client_factory: type[foghttp.AsyncClient],
) -> None:
    client = async_client_factory()
    await client.aclose()

    with pytest.raises(foghttp.ClientClosedError, match="FogHTTP client is closed"):
        client.stats()


async def test_async_dump_transport_state_before_first_request_do_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    state = client.dump_transport_state()
    await client.aclose()

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
        "idle_timeout_evictions": 0,
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


async def test_async_close_closes_opened_raw_client_once(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    async_noop_transport: None,
    faker: Faker,
) -> None:
    client = async_client_factory()

    await client.get(faker.url())
    await client.aclose()
    await client.aclose()

    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1


async def test_async_context_manager_without_request_does_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
) -> None:
    async with async_client_factory():
        pass

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


@pytest.mark.parametrize("client_options", [{}, {"runtime": "dedicated"}])
async def test_async_short_lived_clients_without_requests_do_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    client_options: dict[str, object],
) -> None:
    for _index in range(SHORT_LIVED_CLIENT_COUNT):
        client = async_client_factory(**client_options)
        await client.aclose()

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0


async def test_async_reuses_lazy_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
    async_noop_transport: None,
    faker: Faker,
) -> None:
    urls = [faker.url(), faker.url()]

    async with async_client_factory() as client:
        await client.get(urls[0])
        await client.get(urls[1])

    assert raw_client_factory.calls == 1


async def test_async_concurrent_first_requests_share_lazy_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
    async_noop_transport: None,
    faker: Faker,
) -> None:
    urls = [faker.url(), faker.url()]

    async with async_client_factory() as client:
        await asyncio.gather(
            client.get(urls[0]),
            client.get(urls[1]),
        )

    assert raw_client_factory.calls == 1


async def test_async_context_manager_closes_opened_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    async_noop_transport: None,
    faker: Faker,
) -> None:
    async with async_client_factory() as client:
        await client.get(faker.url())

    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1
