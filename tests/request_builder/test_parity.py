import importlib

from faker import Faker
import orjson
import pytest

import foghttp


def test_sync_build_request_prepares_request_without_transport(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fail_on_transport_creation("foghttp.client", monkeypatch)

    with foghttp.Client() as client:
        request = client.build_request("GET", faker.url())

    assert request.method == "GET"


async def test_async_build_request_prepares_request_without_transport(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fail_on_transport_creation("foghttp.async_client", monkeypatch)

    async with foghttp.AsyncClient() as client:
        request = client.build_request("GET", faker.url())

    assert request.method == "GET"


async def test_sync_and_async_build_request_have_same_prepared_request(faker: Faker) -> None:
    payload = {"name": faker.name()}
    url = "HTTPS://Example.COM:443/users?debug=1#profile"
    headers = foghttp.Headers([("Accept", "application/json"), ("X-Trace", faker.word())])
    params = [("tag", "rust"), ("tag", "python"), ("q", "fog http")]

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(
            "post",
            url,
            headers=headers,
            params=params,
            json=payload,
        )

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(
            "post",
            url,
            headers=headers,
            params=params,
            json=payload,
        )

    expected_url = "https://example.com/users?debug=1&tag=rust&tag=python&q=fog+http#profile"
    expected_body = orjson.dumps(payload)

    assert sync_request.method == "POST"
    assert async_request.method == "POST"
    assert sync_request.url == expected_url
    assert async_request.url == expected_url
    assert sync_request.headers.multi_items() == async_request.headers.multi_items()
    assert sync_request.content == expected_body
    assert async_request.content == expected_body


def _fail_on_transport_creation(module_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    client_module = importlib.import_module(module_name)

    def create_raw_client_probe(*_args: object, **_kwargs: object) -> object:
        msg = "build_request() must not create a RawClient"
        raise AssertionError(msg)

    monkeypatch.setattr(client_module, "create_raw_client", create_raw_client_probe)
