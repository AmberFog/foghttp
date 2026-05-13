import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from faker import Faker
import pytest

import foghttp

from .helpers import CloseTrackingRawClient, RawClientFactory


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

    assert stats == foghttp.PoolStats()
    assert raw_client_factory.calls == 0


def test_sync_closed_client_rejects_stats(
    sync_client_factory: type[foghttp.Client],
) -> None:
    client = sync_client_factory()
    client.close()

    with pytest.raises(foghttp.ClientClosedError):
        client.stats()


def test_sync_dump_pool_state_before_first_request_do_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
) -> None:
    client = sync_client_factory()

    state = client.dump_pool_state()
    client.close()

    assert state == {
        "active_connections": 0,
        "idle_connections": 0,
        "pending_acquires": 0,
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

    assert stats == foghttp.PoolStats()
    assert raw_client_factory.calls == 0


async def test_async_closed_client_rejects_stats(
    async_client_factory: type[foghttp.AsyncClient],
) -> None:
    client = async_client_factory()
    await client.aclose()

    with pytest.raises(foghttp.ClientClosedError):
        client.stats()


async def test_async_dump_pool_state_before_first_request_do_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    state = client.dump_pool_state()
    await client.aclose()

    assert state == {
        "active_connections": 0,
        "idle_connections": 0,
        "pending_acquires": 0,
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
