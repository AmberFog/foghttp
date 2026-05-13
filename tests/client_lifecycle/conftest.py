from collections.abc import Iterator
import importlib

import pytest

import foghttp

from .helpers import CloseTrackingRawClient, RawClientFactory


@pytest.fixture
def raw_client() -> CloseTrackingRawClient:
    return CloseTrackingRawClient()


@pytest.fixture
def raw_client_factory(raw_client: CloseTrackingRawClient) -> RawClientFactory:
    return RawClientFactory(raw_client)


@pytest.fixture
def sync_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client_factory: RawClientFactory,
) -> Iterator[type[foghttp.Client]]:
    client_module = importlib.import_module("foghttp.client")
    monkeypatch.setattr(client_module, "create_raw_client", raw_client_factory.create)
    yield foghttp.Client


@pytest.fixture
def async_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client_factory: RawClientFactory,
) -> Iterator[type[foghttp.AsyncClient]]:
    client_module = importlib.import_module("foghttp.async_client")
    monkeypatch.setattr(client_module, "create_raw_client", raw_client_factory.create)
    yield foghttp.AsyncClient


@pytest.fixture
def sync_noop_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client_module = importlib.import_module("foghttp.client")

    def fake_send_raw_request(**_kwargs: object) -> object:
        return object()

    def fake_response_from_raw(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(client_module, "send_raw_request", fake_send_raw_request)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)


@pytest.fixture
def async_noop_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    client_module = importlib.import_module("foghttp.async_client")

    async def fake_send_raw_request_async(**_kwargs: object) -> object:
        return object()

    def fake_response_from_raw(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(client_module, "send_raw_request_async", fake_send_raw_request_async)
    monkeypatch.setattr(client_module, "response_from_raw", fake_response_from_raw)
