from faker import Faker
import orjson
import pytest

import foghttp


def test_request_normalizes_method_url_and_copies_headers() -> None:
    headers = foghttp.Headers([("x-repeat", "one")])

    request = foghttp.Request(
        "get",
        "HTTPS://Example.COM:443/users",
        headers=headers,
        content=b"payload",
    )
    headers.add("x-repeat", "two")

    assert request.method == "GET"
    assert request.url == "https://example.com/users"
    assert request.headers.get_list("x-repeat") == ["one"]
    assert request.content == b"payload"
    assert repr(request) == "Request('GET', 'https://example.com/users')"


def test_client_build_request_prepares_url_headers_and_json(
    sync_http_server: str,
    faker: Faker,
) -> None:
    source_headers = {"accept": "application/json"}
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        request = client.build_request(
            "post",
            sync_http_server + "/users?debug=1",
            headers=source_headers,
            params={"tag": ["rust", "python"]},
            json=payload,
        )

    assert source_headers == {"accept": "application/json"}
    assert request.method == "POST"
    assert request.url == sync_http_server + "/users?debug=1&tag=rust&tag=python"
    assert request.headers["accept"] == "application/json"
    assert request.headers["content-type"] == "application/json"
    assert request.content == orjson.dumps(payload)


def test_client_build_request_rejects_content_and_json(sync_http_server: str, faker: Faker) -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match="pass either content or json"):
        client.build_request(
            "POST",
            sync_http_server + "/users",
            content=b"raw",
            json={"name": faker.name()},
        )
