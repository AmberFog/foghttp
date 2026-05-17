from urllib.parse import urlsplit

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, POST
from foghttp.status_codes.redirect import (
    FOUND,
    MOVED_PERMANENTLY,
    PERMANENT_REDIRECT,
    REDIRECT_STATUS_CODES,
    SEE_OTHER,
    TEMPORARY_REDIRECT,
)
from foghttp.status_codes.success import OK
from tests.redirect_helpers import (
    REDIRECT_SECURITY_HEADERS,
    SECURITY_HEADERS_PATH,
    header_values,
    redirect_to_location_url,
)


POST_REDIRECTS_TO_GET_STATUS_CODES = (MOVED_PERMANENTLY, FOUND, SEE_OTHER)
POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES = (TEMPORARY_REDIRECT, PERMANENT_REDIRECT)


async def test_get_follows_redirects(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in REDIRECT_STATUS_CODES:
            response = await client.get(f"{http_server}/redirect/{status_code}")

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.request.method == GET
            assert response.request.url == f"{http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].url == f"{http_server}/redirect/{status_code}"
            assert response.history[0].request.method == GET
            assert response.history[0].request.url == f"{http_server}/redirect/{status_code}"


async def test_head_follows_redirects(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.head(f"{http_server}/redirect/{FOUND}")

    assert response.status_code == OK
    assert response.url == f"{http_server}/final"
    assert response.content == b""
    assert len(response.history) == 1


async def test_get_redirects_respect_limit(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True, max_redirects=1) as client:
        with pytest.raises(foghttp.RequestError, match="redirect limit exceeded"):
            await client.get(f"{http_server}/loop")


async def test_get_redirects_are_disabled_by_default(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(f"{http_server}/redirect/{FOUND}")

    assert response.status_code == FOUND
    assert response.url == f"{http_server}/redirect/{FOUND}"
    assert response.history == ()


async def test_post_redirects_rewrite_to_get(http_server: str, faker: Faker) -> None:
    post_body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_TO_GET_STATUS_CODES:
            response = await client.post(
                f"{http_server}/redirect/{status_code}",
                content=post_body,
            )

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.request.method == GET
            assert response.request.url == f"{http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert response.json()["body"] == ""
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == POST
            assert response.history[0].request.url == f"{http_server}/redirect/{status_code}"


async def test_post_redirects_preserve_method_and_body(http_server: str, faker: Faker) -> None:
    post_body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES:
            response = await client.post(
                f"{http_server}/redirect/{status_code}",
                content=post_body,
            )

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.request.method == POST
            assert response.request.url == f"{http_server}/final"
            assert response.json()["request_line"] == "POST /final HTTP/1.1"
            assert response.json()["body"] == post_body
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == POST
            assert response.history[0].request.url == f"{http_server}/redirect/{status_code}"


async def test_same_origin_redirect_preserves_sensitive_headers(http_server: str) -> None:
    location = f"{http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=FOUND, location=location)

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, headers=REDIRECT_SECURITY_HEADERS)

    payload = response.json()
    assert header_values(payload, "authorization") == ["Bearer secret"]
    assert header_values(payload, "proxy-authorization") == ["Basic proxy-secret"]
    assert header_values(payload, "cookie") == ["session=secret"]
    assert header_values(payload, "host") == [urlsplit(http_server).netloc]
    assert header_values(payload, "origin") == ["https://example.com"]
    assert header_values(payload, "referer") == ["https://example.com/source"]


async def test_cross_origin_redirect_strips_sensitive_headers(
    http_server: str,
    secondary_http_server: str,
) -> None:
    location = f"{secondary_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=FOUND, location=location)

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, headers=REDIRECT_SECURITY_HEADERS)

    payload = response.json()
    assert header_values(payload, "accept") == ["application/json"]
    assert header_values(payload, "authorization") == []
    assert header_values(payload, "proxy-authorization") == []
    assert header_values(payload, "cookie") == []
    assert header_values(payload, "host") == [urlsplit(secondary_http_server).netloc]
    assert header_values(payload, "origin") == []
    assert header_values(payload, "referer") == []


async def test_post_redirect_rewrite_strips_body_headers(http_server: str, faker: Faker) -> None:
    location = f"{http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=SEE_OTHER, location=location)
    post_body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            url,
            headers={
                "authorization": "Bearer secret",
                "content-encoding": "identity",
                "content-type": "text/plain",
            },
            content=post_body,
        )

    payload = response.json()
    assert payload["request_line"] == f"GET {SECURITY_HEADERS_PATH} HTTP/1.1"
    assert payload["body"] == ""
    assert header_values(payload, "authorization") == ["Bearer secret"]
    assert header_values(payload, "content-encoding") == []
    assert header_values(payload, "content-type") == []


async def test_post_redirect_preserving_method_keeps_body_headers(http_server: str, faker: Faker) -> None:
    location = f"{http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=TEMPORARY_REDIRECT, location=location)
    post_body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            url,
            headers={"content-type": "text/plain"},
            content=post_body,
        )

    payload = response.json()
    assert payload["request_line"] == f"POST {SECURITY_HEADERS_PATH} HTTP/1.1"
    assert payload["body"] == post_body
    assert header_values(payload, "content-type") == ["text/plain"]


@pytest.mark.parametrize("status_code", POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES)
async def test_cross_origin_post_redirect_drops_body_replay(
    http_server: str,
    secondary_http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    location = f"{secondary_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(
        http_server,
        status_code=status_code,
        location=location,
    )
    post_body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            url,
            headers={
                **REDIRECT_SECURITY_HEADERS,
                "content-encoding": "identity",
                "content-type": "text/plain",
            },
            content=post_body,
        )

    payload = response.json()
    assert payload["request_line"] == f"POST {SECURITY_HEADERS_PATH} HTTP/1.1"
    assert payload["body"] == ""
    assert header_values(payload, "accept") == ["application/json"]
    assert header_values(payload, "authorization") == []
    assert header_values(payload, "content-encoding") == []
    assert header_values(payload, "content-type") == []
    assert header_values(payload, "cookie") == []
    assert header_values(payload, "host") == [urlsplit(secondary_http_server).netloc]
    assert header_values(payload, "origin") == []
    assert header_values(payload, "proxy-authorization") == []
    assert header_values(payload, "referer") == []
