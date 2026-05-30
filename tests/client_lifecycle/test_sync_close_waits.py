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
    transport_module = importlib.import_module("foghttp._client.transport")

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

    monkeypatch.setattr(transport_module, "send_raw_request", fake_send_raw_request)
    monkeypatch.setattr(transport_module, "response_from_raw", fake_response_from_raw)
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
