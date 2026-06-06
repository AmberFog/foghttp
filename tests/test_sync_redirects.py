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
from tests.request_factories import non_replayable_request


POST_REDIRECTS_TO_GET_STATUS_CODES = (MOVED_PERMANENTLY, FOUND, SEE_OTHER)
POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES = (TEMPORARY_REDIRECT, PERMANENT_REDIRECT)
METHOD_PRESERVING_REDIRECT_PARAMS = (
    pytest.param(TEMPORARY_REDIRECT, id="307-temporary"),
    pytest.param(PERMANENT_REDIRECT, id="308-permanent"),
)


def test_get_follows_redirects(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        for status_code in REDIRECT_STATUS_CODES:
            response = client.get(f"{sync_http_server}/redirect/{status_code}")

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == GET
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].url == f"{sync_http_server}/redirect/{status_code}"
            assert response.history[0].request.method == GET
            assert response.history[0].request.url == f"{sync_http_server}/redirect/{status_code}"


def test_head_follows_redirects(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        response = client.head(f"{sync_http_server}/redirect/{FOUND}")

    assert response.status_code == OK
    assert response.url == f"{sync_http_server}/final"
    assert response.content == b""
    assert len(response.history) == 1


def test_get_redirects_respect_limit(sync_http_server: str) -> None:
    with (
        foghttp.Client(follow_redirects=True, max_redirects=1) as client,
        pytest.raises(foghttp.RequestError, match="redirect limit exceeded"),
    ):
        client.get(f"{sync_http_server}/loop")


def test_post_redirects_rewrite_to_get(sync_http_server: str, faker: Faker) -> None:
    post_body = faker.sentence()

    with foghttp.Client(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_TO_GET_STATUS_CODES:
            response = client.post(
                f"{sync_http_server}/redirect/{status_code}",
                content=post_body,
            )

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == GET
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert response.json()["body"] == ""
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == POST
            assert response.history[0].request.url == f"{sync_http_server}/redirect/{status_code}"


def test_post_redirects_preserve_method_and_body(sync_http_server: str, faker: Faker) -> None:
    post_body = faker.sentence()

    with foghttp.Client(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES:
            response = client.post(
                f"{sync_http_server}/redirect/{status_code}",
                content=post_body,
            )

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == POST
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "POST /final HTTP/1.1"
            assert response.json()["body"] == post_body
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == POST
            assert response.history[0].request.url == f"{sync_http_server}/redirect/{status_code}"


@pytest.mark.parametrize("status_code", METHOD_PRESERVING_REDIRECT_PARAMS)
def test_post_method_preserving_redirect_rejects_non_replayable_body(
    sync_http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    request = non_replayable_request(
        POST,
        f"{sync_http_server}/redirect/{status_code}",
        content=faker.binary(length=16),
    )

    with foghttp.Client(follow_redirects=True) as client:
        with pytest.raises(foghttp.RequestError, match="non-replayable request body"):
            client.send(request)

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0


def test_same_origin_redirect_preserves_sensitive_headers(sync_http_server: str) -> None:
    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)

    with foghttp.Client(follow_redirects=True) as client:
        response = client.get(url, headers=REDIRECT_SECURITY_HEADERS)

    payload = response.json()
    assert header_values(payload, "authorization") == ["Bearer secret"]
    assert header_values(payload, "proxy-authorization") == []
    assert header_values(payload, "cookie") == ["session=secret"]
    assert header_values(payload, "host") == [urlsplit(sync_http_server).netloc]
    assert header_values(payload, "origin") == ["https://example.com"]
    assert header_values(payload, "referer") == ["https://example.com/source"]


def test_cross_origin_redirect_strips_sensitive_headers(
    sync_http_server: str,
    secondary_sync_http_server: str,
) -> None:
    location = f"{secondary_sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=FOUND, location=location)

    with foghttp.Client(follow_redirects=True) as client:
        response = client.get(url, headers=REDIRECT_SECURITY_HEADERS)

    payload = response.json()
    assert header_values(payload, "accept") == ["application/json"]
    assert header_values(payload, "authorization") == []
    assert header_values(payload, "proxy-authorization") == []
    assert header_values(payload, "cookie") == []
    assert header_values(payload, "host") == [urlsplit(secondary_sync_http_server).netloc]
    assert header_values(payload, "origin") == []
    assert header_values(payload, "referer") == []


def test_post_redirect_rewrite_strips_body_headers(sync_http_server: str, faker: Faker) -> None:
    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=SEE_OTHER, location=location)
    post_body = faker.sentence()

    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
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


def test_post_redirect_preserving_method_keeps_body_headers(sync_http_server: str, faker: Faker) -> None:
    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(sync_http_server, status_code=TEMPORARY_REDIRECT, location=location)
    post_body = faker.sentence()

    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
            url,
            headers={"content-type": "text/plain"},
            content=post_body,
        )

    payload = response.json()
    assert payload["request_line"] == f"POST {SECURITY_HEADERS_PATH} HTTP/1.1"
    assert payload["body"] == post_body
    assert header_values(payload, "content-type") == ["text/plain"]


@pytest.mark.parametrize("status_code", POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES)
def test_cross_origin_post_redirect_drops_body_replay(
    sync_http_server: str,
    secondary_sync_http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    location = f"{secondary_sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(
        sync_http_server,
        status_code=status_code,
        location=location,
    )
    post_body = faker.sentence()

    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
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
    assert header_values(payload, "host") == [urlsplit(secondary_sync_http_server).netloc]
    assert header_values(payload, "origin") == []
    assert header_values(payload, "proxy-authorization") == []
    assert header_values(payload, "referer") == []
