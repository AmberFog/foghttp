from urllib.parse import urlencode, urlsplit, urlunsplit

import foghttp
from foghttp.status_codes.success import OK
from tests.redirect_helpers import header_values
from tests.support.http_routes import (
    COOKIE_REDIRECT_PATH,
    REPEATED_HEADERS_PATH,
    SECURITY_HEADERS_PATH,
)

from .assertions import cookie_pairs


async def test_async_cookie_jar_stores_and_sends_repeated_headers(http_server: str) -> None:
    async with foghttp.AsyncClient(cookies=True) as client:
        await client.get(http_server + REPEATED_HEADERS_PATH)
        response = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(response.json(), "cookie")) == {"first=1", "second=2"}


async def test_async_cookie_jar_does_not_leak_across_host_redirect(
    http_server: str,
) -> None:
    target = _localhost_url(http_server, SECURITY_HEADERS_PATH)
    redirect = f"{http_server}{COOKIE_REDIRECT_PATH}?{urlencode({'location': target})}"

    async with foghttp.AsyncClient(cookies=True, follow_redirects=True) as client:
        response = await client.get(redirect)

    assert response.status_code == OK
    assert header_values(response.json(), "cookie") == []


async def test_async_cookie_jar_updates_before_stream_is_exposed(http_server: str) -> None:
    async with foghttp.AsyncClient(cookies=True) as client:
        async with client.stream("GET", http_server + REPEATED_HEADERS_PATH) as response:
            assert response.status_code == OK
        echoed = await client.get(http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(echoed.json(), "cookie")) == {"first=1", "second=2"}


def _localhost_url(base_url: str, path: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, f"localhost:{parts.port}", path, "", ""))
