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


async def test_get_follows_redirects(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in REDIRECT_STATUS_CODES:
            response = await client.get(f"{http_server}/redirect/{status_code}")

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].url == f"{http_server}/redirect/{status_code}"


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


async def test_post_redirects_rewrite_to_get(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_TO_GET_STATUS_CODES:
            response = await client.post(
                f"{http_server}/redirect/{status_code}",
                content=POST_BODY,
            )

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert response.json()["body"] == ""
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code


async def test_post_redirects_preserve_method_and_body(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        for status_code in POST_REDIRECTS_PRESERVE_METHOD_STATUS_CODES:
            response = await client.post(
                f"{http_server}/redirect/{status_code}",
                content=POST_BODY,
            )

            assert response.status_code == OK
            assert response.url == f"{http_server}/final"
            assert response.json()["request_line"] == "POST /final HTTP/1.1"
            assert response.json()["body"] == POST_BODY
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
