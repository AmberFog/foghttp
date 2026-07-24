from urllib.parse import urlencode, urlsplit, urlunsplit

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.http_body_scenarios import INCOMPLETE_CHUNKED_BODY_PATH
from tests.redirect_helpers import header_values
from tests.support.http_routes import (
    COOKIE_BODY_PATH,
    COOKIE_OPAQUE_PATH,
    COOKIE_REDIRECT_PATH,
    COOKIE_ROOT_SET_PATH,
    REPEATED_HEADERS_PATH,
    SECURITY_HEADERS_PATH,
)

from .assertions import cookie_pairs


async def test_async_cookie_jar_stores_and_sends_repeated_headers(http_server: str) -> None:
    async with foghttp.AsyncClient(cookies=True) as client:
        await client.get(http_server + REPEATED_HEADERS_PATH)
        response = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(response.json(), "cookie")) == {"first=1", "second=2"}


async def test_async_cookie_jar_reselects_for_cross_host_redirect(
    http_server: str,
) -> None:
    target = _localhost_url(http_server, SECURITY_HEADERS_PATH)
    redirect = f"{http_server}{COOKIE_REDIRECT_PATH}?{urlencode({'location': target})}"

    async with foghttp.AsyncClient(cookies=True, follow_redirects=True) as client:
        await client.get(_localhost_url(http_server, COOKIE_ROOT_SET_PATH))
        response = await client.get(
            redirect,
            headers={"Cookie": "source=caller-secret"},
        )

    assert response.status_code == OK
    assert cookie_pairs(header_values(response.json(), "cookie")) == {
        "root=cookie-secret",
    }


async def test_async_cookie_jar_ignores_obs_text_pair_without_losing_valid_siblings(
    http_server: str,
) -> None:
    async with foghttp.AsyncClient(cookies=True) as client:
        await client.get(http_server + COOKIE_OPAQUE_PATH)
        response = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(response.json(), "cookie")) == {
        'quoted="a%2Fb"',
        "ascii=sibling",
        "empty=",
        "encoded=%FF",
        "equals=a=b",
        "literal=100%",
        "nameless-token",
        "opaque=%41%2F%25",
    }


async def test_async_cookie_jar_updates_before_stream_is_exposed(http_server: str) -> None:
    async with (
        foghttp.AsyncClient(cookies=True) as client,
        client.stream("GET", http_server + COOKIE_BODY_PATH) as response,
    ):
        assert response.status_code == OK
        echoed = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(echoed.json(), "cookie")) == {
        "retry_session=cookie-secret",
    }


async def test_async_cookie_jar_commits_before_incomplete_body_timeout(
    http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=0.05)
    async with foghttp.AsyncClient(cookies=True, timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired"):
            await client.get(http_server + INCOMPLETE_CHUNKED_BODY_PATH)
        verification = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(verification.json(), "cookie")) == {
        "incomplete_session=cookie-secret",
    }


def _localhost_url(base_url: str, path: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, f"localhost:{parts.port}", path, "", ""))
