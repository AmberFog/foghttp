from collections.abc import Iterator
import importlib

import pytest

import foghttp

from .helpers import CloseTrackingRawClient


@pytest.fixture
def raw_client() -> CloseTrackingRawClient:
    return CloseTrackingRawClient()


@pytest.fixture
def sync_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client: CloseTrackingRawClient,
) -> Iterator[type[foghttp.Client]]:
    client_module = importlib.import_module("foghttp.client")
    monkeypatch.setattr(client_module, "create_raw_client", lambda **_kwargs: raw_client)
    yield foghttp.Client


@pytest.fixture
def async_client_factory(
    monkeypatch: pytest.MonkeyPatch,
    raw_client: CloseTrackingRawClient,
) -> Iterator[type[foghttp.AsyncClient]]:
    client_module = importlib.import_module("foghttp.async_client")
    monkeypatch.setattr(client_module, "create_raw_client", lambda **_kwargs: raw_client)
    yield foghttp.AsyncClient
