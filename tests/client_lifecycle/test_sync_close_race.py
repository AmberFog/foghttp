from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
import importlib
import threading

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET

from .helpers import (
    CloseTrackingRawClient,
    RawClientFactory,
    wait_until_sync_client_closed,
)


def test_sync_close_waits_for_send_in_validation_window(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    faker: Faker,
) -> None:
    client_module = importlib.import_module("foghttp.client")
    validation_started = threading.Event()
    release_validation = threading.Event()
    close_returned = threading.Event()
    raw_close_started = threading.Event()
    raw_response = object()
    response = object()

    def fake_validate_safe_request_headers(_headers: foghttp.Headers) -> None:
        validation_started.set()
        if not release_validation.wait(timeout=1.0):
            msg = "validation release event was not set"
            raise AssertionError(msg)

    def fake_send_raw_request(**_kwargs: object) -> object:
        return raw_response

    def fake_response_from_raw(**_kwargs: object) -> object:
        return response

    def fake_close_raw_client(raw_client_to_close: CloseTrackingRawClient) -> None:
        raw_close_started.set()
        raw_client_to_close.close()

    monkeypatch.setattr(
        client_module,
        "validate_safe_request_headers",
        fake_validate_safe_request_headers,
    )
    monkeypatch.setattr(client_module, "send_raw_request", fake_send_raw_request)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)
    monkeypatch.setattr(client_module, "close_raw_client", fake_close_raw_client)

    client = sync_client_factory()
    request = client.build_request(GET, faker.url())

    def close_client() -> None:
        client.close()
        close_returned.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        request_future = executor.submit(client.send, request)
        assert validation_started.wait(timeout=1.0)

        close_future = executor.submit(close_client)
        wait_until_sync_client_closed(client)

        with pytest.raises(FutureTimeoutError):
            close_future.result(timeout=0.05)
        assert not close_returned.is_set()
        assert not raw_close_started.wait(timeout=0.05)
        assert raw_client_factory.calls == 0
        assert raw_client.close_calls == 0

        release_validation.set()
        assert request_future.result(timeout=1.0) is response
        close_future.result(timeout=1.0)

    assert close_returned.is_set()
    assert raw_close_started.is_set()
    assert raw_client_factory.calls == 1
    assert raw_client.close_calls == 1


def test_sync_send_validation_error_releases_concurrent_close(
    sync_client_factory: type[foghttp.Client],
    raw_client: CloseTrackingRawClient,
    raw_client_factory: RawClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    faker: Faker,
) -> None:
    client_module = importlib.import_module("foghttp.client")
    validation_started = threading.Event()
    release_validation = threading.Event()

    def fake_validate_safe_request_headers(_headers: foghttp.Headers) -> None:
        validation_started.set()
        if not release_validation.wait(timeout=1.0):
            msg = "validation release event was not set"
            raise AssertionError(msg)
        msg = "invalid request header"
        raise ValueError(msg)

    monkeypatch.setattr(
        client_module,
        "validate_safe_request_headers",
        fake_validate_safe_request_headers,
    )

    client = sync_client_factory()
    request = client.build_request(GET, faker.url())

    with ThreadPoolExecutor(max_workers=2) as executor:
        request_future = executor.submit(client.send, request)
        assert validation_started.wait(timeout=1.0)

        close_future = executor.submit(client.close)
        wait_until_sync_client_closed(client)

        with pytest.raises(FutureTimeoutError):
            close_future.result(timeout=0.05)

        release_validation.set()
        with pytest.raises(ValueError, match="invalid request header"):
            request_future.result(timeout=1.0)
        close_future.result(timeout=1.0)

    assert raw_client_factory.calls == 0
    assert raw_client.close_calls == 0
