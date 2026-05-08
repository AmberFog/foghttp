import pytest

import foghttp
from foghttp.status_codes.redirect import (
    FOUND,
    MOVED_PERMANENTLY,
    PERMANENT_REDIRECT,
    REDIRECT_STATUS_CODES,
    SEE_OTHER,
    TEMPORARY_REDIRECT,
)
from foghttp.status_codes.success import OK


POST_REDIRECTS_TO_GET_STATUS_CODES = (MOVED_PERMANENTLY, FOUND, SEE_OTHER)
POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES = (TEMPORARY_REDIRECT, PERMANENT_REDIRECT)
POST_BODY = "redirect-body"


def test_get_follows_redirects(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        for status_code in REDIRECT_STATUS_CODES:
            response = client.get(f"{sync_http_server}/redirect/{status_code}")

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == "GET"
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].url == f"{sync_http_server}/redirect/{status_code}"
            assert response.history[0].request.method == "GET"
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


def test_post_redirects_rewrite_to_get(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_TO_GET_STATUS_CODES:
            response = client.post(
                f"{sync_http_server}/redirect/{status_code}",
                content=POST_BODY,
            )

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == "GET"
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert response.json()["body"] == ""
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == "POST"
            assert response.history[0].request.url == f"{sync_http_server}/redirect/{status_code}"


def test_post_redirects_preserve_method_and_body(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES:
            response = client.post(
                f"{sync_http_server}/redirect/{status_code}",
                content=POST_BODY,
            )

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.request.method == "POST"
            assert response.request.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "POST /final HTTP/1.1"
            assert response.json()["body"] == POST_BODY
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].request.method == "POST"
            assert response.history[0].request.url == f"{sync_http_server}/redirect/{status_code}"
