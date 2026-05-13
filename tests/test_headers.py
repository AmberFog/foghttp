from faker import Faker
import pytest

import foghttp
from foghttp.status_codes.success import OK


def test_headers_are_case_insensitive_mapping() -> None:
    headers = foghttp.Headers([("Content-Type", "application/json")])

    assert headers["content-type"] == "application/json"
    assert headers["CONTENT-TYPE"] == "application/json"
    assert "Content-Type" in headers
    assert "content-type" in headers
    assert dict(headers) == {"Content-Type": "application/json"}


def test_headers_preserve_repeated_values() -> None:
    headers = foghttp.Headers(
        [
            ("Set-Cookie", "first=1"),
            ("set-cookie", "second=2"),
        ],
    )

    assert len(headers) == 1
    assert headers["set-cookie"] == "second=2"
    assert list(headers) == ["Set-Cookie"]
    assert headers.get_list("SET-COOKIE") == ["first=1", "second=2"]
    assert headers.multi_items() == [("Set-Cookie", "first=1"), ("set-cookie", "second=2")]


def test_headers_delete_removes_repeated_values(faker: Faker) -> None:
    first_value, second_value = faker.words(nb=2, unique=True)
    headers = foghttp.Headers([("x-trace", first_value), ("X-Trace", second_value)])

    del headers["X-Trace"]

    assert "x-trace" not in headers
    assert headers.get_list("x-trace") == []
    assert headers.multi_items() == []


def test_headers_delete_missing_name_raises_key_error() -> None:
    headers = foghttp.Headers()

    with pytest.raises(KeyError) as exc_info:
        del headers["missing"]

    assert exc_info.value.args == ("missing",)


def test_headers_repr_shows_multi_items(faker: Faker) -> None:
    value = faker.word()
    headers = foghttp.Headers([("x-trace", value)])

    assert repr(headers) == f"Headers([('x-trace', '{value}')])"


def test_headers_set_replaces_repeated_values(faker: Faker) -> None:
    first_value, second_value, replacement = faker.words(nb=3, unique=True)
    headers = foghttp.Headers([("x-trace", first_value), ("X-Trace", second_value)])

    headers["X-Trace"] = replacement

    assert headers["x-trace"] == replacement
    assert headers.get_list("x-trace") == [replacement]
    assert headers.multi_items() == [("X-Trace", replacement)]


def test_headers_copy_is_independent(faker: Faker) -> None:
    first_value, second_value = faker.words(nb=2, unique=True)
    headers = foghttp.Headers([("x-trace", first_value)])
    copied = headers.copy()

    copied.add("x-trace", second_value)

    assert headers.get_list("x-trace") == [first_value]
    assert copied.get_list("x-trace") == [first_value, second_value]


def test_sync_response_preserves_repeated_headers(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_http_server + "/headers/repeated")

    assert response.status_code == OK
    assert response.headers["set-cookie"] == "second=2"
    assert response.headers.get_list("set-cookie") == ["first=1", "second=2"]
    assert response.headers.get_list("x-trace") == ["one", "two"]


async def test_async_response_preserves_repeated_headers(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(http_server + "/headers/repeated")

    assert response.status_code == OK
    assert response.headers["set-cookie"] == "second=2"
    assert response.headers.get_list("set-cookie") == ["first=1", "second=2"]
    assert response.headers.get_list("x-trace") == ["one", "two"]


def test_sync_request_sends_repeated_headers(sync_http_server: str, faker: Faker) -> None:
    values = faker.words(nb=2, unique=True)
    headers = foghttp.Headers([("x-repeat", values[0]), ("X-Repeat", values[1])])

    with foghttp.Client() as client:
        response = client.get(sync_http_server + "/headers/echo", headers=headers)

    assert response.json()["x-repeat"] == values
    assert response.request.headers.get_list("x-repeat") == values


async def test_async_request_sends_repeated_headers(http_server: str, faker: Faker) -> None:
    values = faker.words(nb=2, unique=True)
    headers = foghttp.Headers([("x-repeat", values[0]), ("X-Repeat", values[1])])

    async with foghttp.AsyncClient() as client:
        response = await client.get(http_server + "/headers/echo", headers=headers)

    assert response.json()["x-repeat"] == values
    assert response.request.headers.get_list("x-repeat") == values
