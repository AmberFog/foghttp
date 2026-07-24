from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.methods import GET, POST


def test_sync_build_request_prepares_request_without_transport(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fail_on_transport_creation(monkeypatch)

    with foghttp.Client() as client:
        request = client.build_request(GET, faker.url())

    assert request.method == GET


async def test_async_build_request_prepares_request_without_transport(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fail_on_transport_creation(monkeypatch)

    async with foghttp.AsyncClient() as client:
        request = client.build_request(GET, faker.url())

    assert request.method == GET


async def test_sync_and_async_build_request_have_same_prepared_request(faker: Faker) -> None:
    payload = {"name": faker.name()}
    url = "HTTPS://Example.COM:443/users?debug=1#profile"
    headers = foghttp.Headers([("Accept", "application/json"), ("X-Trace", faker.word())])
    params = [("tag", "rust"), ("tag", "python"), ("q", "fog http")]

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(
            POST.lower(),
            url,
            headers=headers,
            params=params,
            json=payload,
        )

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(
            POST.lower(),
            url,
            headers=headers,
            params=params,
            json=payload,
        )

    expected_url = "https://example.com/users?debug=1&tag=rust&tag=python&q=fog+http#profile"
    expected_body = orjson.dumps(payload)

    assert sync_request.method == POST
    assert async_request.method == POST
    assert sync_request.url == expected_url
    assert async_request.url == expected_url
    assert sync_request.headers.multi_items() == async_request.headers.multi_items()
    assert sync_request.content == expected_body
    assert async_request.content == expected_body


async def test_sync_and_async_build_request_have_same_form_data_body(faker: Faker) -> None:
    data = {"name": faker.name(), "scope": ["read", "write"]}
    url = faker.url()

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(POST, url, data=data)

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(POST, url, data=data)

    assert sync_request.url == async_request.url
    assert sync_request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert async_request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert sync_request.content == async_request.content


async def test_sync_and_async_build_request_normalize_mixed_case_method(faker: Faker) -> None:
    mixed_case_method = "gEt"

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(mixed_case_method, faker.url())

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(mixed_case_method, faker.url())

    assert sync_request.method == GET
    assert async_request.method == GET


def test_build_request_validates_url_before_encoding_body() -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match="relative URL without a base"):
        client.build_request(POST, "not a url", json=object())


def _fail_on_transport_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_raw_client_probe(*_args: object, **_kwargs: object) -> object:
        msg = "build_request() must not create a RawClient"
        raise AssertionError(msg)

    monkeypatch.setattr("foghttp._client.core.create_raw_client", create_raw_client_probe)
