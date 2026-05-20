import asyncio
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
import importlib
import threading

from faker import Faker
import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import BLOCKING_RESPONSE_PATH
from .helpers import (
    BlockingSyncHTTPServer,
    CloseTrackingRawClient,
    RawClientFactory,
    wait_until_sync_client_closed,
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

    with pytest.raises(foghttp.ClientClosedError):
        client.stats()


def test_sync_dump_transport_state_before_first_request_do_not_create_raw_client(
    sync_client_factory: type[foghttp.Client],
    raw_client_factory: RawClientFactory,
) -> None:
    client = sync_client_factory()

    state = client.dump_transport_state()
    client.close()

    assert state == {
        "active_requests": 0,
        "buffered_response_bytes": 0,
        "buffered_response_budget_rejections": 0,
        "pending_requests": 0,
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


def test_sync_close_waits_for_in_flight_send(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    faker: Faker,
) -> None:
    client_module = importlib.import_module("foghttp.client")
    request_started = threading.Event()
    release_request = threading.Event()
    close_started = threading.Event()
    close_returned = threading.Event()
    raw_close_started = threading.Event()
    raw_response = object()
    response = object()

    def fake_send_raw_request(**_kwargs: object) -> object:
        request_started.set()
        if not release_request.wait(timeout=1.0):
            msg = "request release event was not set"
            raise AssertionError(msg)
        return raw_response

    def fake_response_from_raw(**_kwargs: object) -> object:
        return response

    def fake_close_raw_client(raw_client_to_close: CloseTrackingRawClient) -> None:
        raw_close_started.set()
        raw_client_to_close.close()

    monkeypatch.setattr(client_module, "send_raw_request", fake_send_raw_request)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)
    monkeypatch.setattr(client_module, "close_raw_client", fake_close_raw_client)

    client = sync_client_factory()

    def close_client() -> None:
        close_started.set()
        client.close()
        close_returned.set()

    with ThreadPoolExecutor(max_workers=3) as executor:
        request_future = executor.submit(client.get, faker.url())
        assert request_started.wait(timeout=1.0)

        close_future = executor.submit(close_client)
        assert close_started.wait(timeout=1.0)
        wait_until_sync_client_closed(client)
        second_close_future = executor.submit(client.close)

        with pytest.raises(foghttp.ClientClosedError):
            client.get(faker.url())
        with pytest.raises(FutureTimeoutError):
            close_future.result(timeout=0.05)
        with pytest.raises(FutureTimeoutError):
            second_close_future.result(timeout=0.05)

        assert not close_returned.is_set()
        assert not raw_close_started.wait(timeout=0.05)
        assert raw_client.close_calls == 0

        release_request.set()
        assert request_future.result(timeout=1.0) is response
        close_future.result(timeout=1.0)
        second_close_future.result(timeout=1.0)

    assert close_returned.is_set()
    assert raw_close_started.is_set()
    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1


def test_sync_close_waits_for_real_in_flight_request(
    sync_blocking_http_server: BlockingSyncHTTPServer,
    faker: Faker,
) -> None:
    client = foghttp.Client()

    def close_client() -> None:
        client.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        request_future = executor.submit(
            client.get,
            sync_blocking_http_server.base_url + BLOCKING_RESPONSE_PATH,
        )
        assert sync_blocking_http_server.request_started.wait(timeout=1.0)

        close_future = executor.submit(close_client)
        wait_until_sync_client_closed(client)

        with pytest.raises(foghttp.ClientClosedError):
            client.get(faker.url())
        with pytest.raises(FutureTimeoutError):
            close_future.result(timeout=0.05)

        sync_blocking_http_server.release_response.set()
        response = request_future.result(timeout=1.0)
        close_future.result(timeout=1.0)

    assert response.status_code == OK
    with pytest.raises(foghttp.ClientClosedError):
        client.get(faker.url())


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


async def test_async_closed_client_rejects_stats(
    async_client_factory: type[foghttp.AsyncClient],
) -> None:
    client = async_client_factory()
    await client.aclose()

    with pytest.raises(foghttp.ClientClosedError):
        client.stats()


async def test_async_dump_transport_state_before_first_request_do_not_create_raw_client(
    async_client_factory: type[foghttp.AsyncClient],
    raw_client_factory: RawClientFactory,
) -> None:
    client = async_client_factory()

    state = client.dump_transport_state()
    await client.aclose()

    assert state == {
        "active_requests": 0,
        "buffered_response_bytes": 0,
        "buffered_response_budget_rejections": 0,
        "pending_requests": 0,
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
