from base64 import b64encode
import json
from urllib.parse import urlsplit

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, POST
from foghttp.status_codes.redirect import FOUND
from tests.client_proxy.environment import clear_proxy_environment
from tests.client_proxy.http_proxy_server import (
    PROXY_REDIRECT_PATH,
    PROXY_STREAM_CHUNK,
    PROXY_STREAM_EARLY_CLOSE_PATH,
    AsyncHTTPProxy,
    ProxyRequest,
    SyncHTTPProxy,
)
from tests.redirect_helpers import redirect_to_location_url
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats


def test_sync_client_routes_http_request_through_explicit_proxy(
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/via-proxy?debug=1")
    content = b"payload"

    with foghttp.Client(proxy=sync_http_proxy.base_url) as client:
        response = client.post(target_url, content=content)

    payload = response.json()
    assert response.request.url == target_url
    assert payload["request_line"] == f"{POST} {target_url} HTTP/1.1"
    assert payload["headers"]["host"] == [urlsplit(target_url).netloc]
    assert payload["headers"].get("proxy-authorization") is None
    assert payload["body"] == content.decode()
    assert len(sync_http_proxy.requests) == 1


def test_sync_stream_routes_http_request_through_explicit_proxy(
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/stream-via-proxy")

    with (
        foghttp.Client(proxy=sync_http_proxy.base_url) as client,
        client.stream(GET, target_url) as response,
    ):
        content = b"".join(response.iter_bytes())

    payload = json.loads(content)
    assert payload["request_line"] == f"{GET} {target_url} HTTP/1.1"
    assert len(sync_http_proxy.requests) == 1


async def test_async_client_routes_http_request_through_explicit_proxy(
    async_http_proxy: AsyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/async-via-proxy")

    async with foghttp.AsyncClient(proxy=async_http_proxy.base_url) as client:
        response = await client.get(target_url)

    payload = response.json()
    assert response.request.url == target_url
    assert payload["request_line"] == f"{GET} {target_url} HTTP/1.1"
    assert payload["headers"]["host"] == [urlsplit(target_url).netloc]
    assert len(async_http_proxy.requests) == 1


async def test_async_stream_routes_http_request_through_explicit_proxy(
    async_http_proxy: AsyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/async-stream-via-proxy")

    async with (
        foghttp.AsyncClient(proxy=async_http_proxy.base_url) as client,
        client.stream(GET, target_url) as response,
    ):
        content = b"".join([chunk async for chunk in response.aiter_bytes()])

    payload = json.loads(content)
    assert payload["request_line"] == f"{GET} {target_url} HTTP/1.1"
    assert len(async_http_proxy.requests) == 1


def test_sync_stream_early_close_through_explicit_proxy_releases_request_slot(
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, PROXY_STREAM_EARLY_CLOSE_PATH)

    with foghttp.Client(proxy=sync_http_proxy.base_url) as client:
        with client.stream(GET, target_url) as response:
            byte_stream = response.iter_bytes()
            assert next(byte_stream) == PROXY_STREAM_CHUNK

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="early-closing a proxied sync stream should abort the body and release the request slot",
        )

    assert len(sync_http_proxy.requests) == 1


async def test_async_stream_early_close_through_explicit_proxy_releases_request_slot(
    async_http_proxy: AsyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, PROXY_STREAM_EARLY_CLOSE_PATH)

    async with foghttp.AsyncClient(proxy=async_http_proxy.base_url) as client:
        async with client.stream(GET, target_url) as response:
            byte_stream = response.aiter_bytes()
            assert await anext(byte_stream) == PROXY_STREAM_CHUNK

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="early-closing a proxied async stream should abort the body and release the request slot",
        )

    assert len(async_http_proxy.requests) == 1


def test_sync_client_sends_proxy_authorization_only_to_proxy(
    faker: Faker,
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    username = faker.user_name()
    password = faker.pystr(min_chars=8, max_chars=8)
    target_url = _target_url(unused_tcp_port, "/proxy-auth")
    proxy_url = f"http://{username}:{password}@{urlsplit(sync_http_proxy.base_url).netloc}"

    with foghttp.Client(proxy=proxy_url) as client:
        response = client.get(target_url)

    payload = response.json()
    assert payload["headers"]["proxy-authorization"] == [_basic_proxy_auth(username, password)]
    assert "proxy-authorization" not in response.request.headers
    assert username not in repr(response.request)
    assert password not in repr(response.request)


def test_trust_env_http_proxy_routes_http_request(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/env-proxy")
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", sync_http_proxy.base_url)

    with foghttp.Client(trust_env=True) as client:
        response = client.get(target_url)

    payload = response.json()
    assert payload["request_line"] == f"{GET} {target_url} HTTP/1.1"
    assert len(sync_http_proxy.requests) == 1


def test_trust_env_all_proxy_routes_http_request(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/all-proxy")
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("ALL_PROXY", sync_http_proxy.base_url)

    with foghttp.Client(trust_env=True) as client:
        response = client.get(target_url)

    payload = response.json()
    assert payload["request_line"] == f"{GET} {target_url} HTTP/1.1"
    assert len(sync_http_proxy.requests) == 1


def test_no_proxy_bypasses_trusted_environment_http_proxy(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_proxy: SyncHTTPProxy,
    sync_http_server: str,
) -> None:
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", sync_http_proxy.base_url)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")

    with foghttp.Client(trust_env=True) as client:
        response = client.get(sync_http_server)

    payload = response.json()
    assert payload["request_line"] == f"{GET} / HTTP/1.1"
    assert sync_http_proxy.requests == []


# HTTPS targets through a proxy are exercised end to end by the CONNECT tunnel
# tests in test_https_proxy_connect.py.


def test_trust_env_no_proxy_cross_origin_redirect_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_proxy: SyncHTTPProxy,
    sync_http_server: str,
    unused_tcp_port: int,
) -> None:
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", sync_http_proxy.base_url)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    target_url = redirect_to_location_url(
        sync_http_server,
        status_code=FOUND,
        location=_target_url(unused_tcp_port, "/redirect-target"),
    )

    with (
        foghttp.Client(trust_env=True, follow_redirects=True) as client,
        pytest.raises(
            foghttp.RequestError,
            match="cross-origin redirect with environment proxy policy",
        ),
    ):
        client.get(target_url)

    assert sync_http_proxy.requests == []


def test_trust_env_http_proxy_cross_origin_redirect_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", sync_http_proxy.base_url)
    redirect_target = "http://redirect-target.example/items"
    target_url = _proxy_redirect_url(unused_tcp_port, redirect_target)

    with (
        foghttp.Client(trust_env=True, follow_redirects=True) as client,
        pytest.raises(
            foghttp.RequestError,
            match="cross-origin redirect with environment proxy policy",
        ),
    ):
        client.get(target_url)

    assert len(sync_http_proxy.requests) == 1


async def test_async_trust_env_http_proxy_cross_origin_redirect_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    async_http_proxy: AsyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", async_http_proxy.base_url)
    redirect_target = "http://redirect-target.example/items"
    target_url = _proxy_redirect_url(unused_tcp_port, redirect_target)

    async with foghttp.AsyncClient(trust_env=True, follow_redirects=True) as client:
        with pytest.raises(
            foghttp.RequestError,
            match="cross-origin redirect with environment proxy policy",
        ):
            await client.get(target_url)

    assert len(async_http_proxy.requests) == 1


def test_explicit_proxy_http_to_http_cross_origin_redirect_uses_same_proxy(
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    redirect_target = "http://redirect-target.example/items"
    target_url = _proxy_redirect_url(unused_tcp_port, redirect_target)

    with foghttp.Client(proxy=sync_http_proxy.base_url, follow_redirects=True) as client:
        response = client.get(target_url)

    payload = response.json()
    assert response.url == redirect_target
    assert payload["request_line"] == f"{GET} {redirect_target} HTTP/1.1"
    assert len(response.history) == 1
    assert response.history[0].url == target_url
    assert _request_lines(sync_http_proxy.requests) == (
        f"{GET} {target_url} HTTP/1.1",
        f"{GET} {redirect_target} HTTP/1.1",
    )


async def test_async_explicit_proxy_http_to_http_cross_origin_redirect_uses_same_proxy(
    async_http_proxy: AsyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    redirect_target = "http://redirect-target.example/items"
    target_url = _proxy_redirect_url(unused_tcp_port, redirect_target)

    async with foghttp.AsyncClient(proxy=async_http_proxy.base_url, follow_redirects=True) as client:
        response = await client.get(target_url)

    payload = response.json()
    assert response.url == redirect_target
    assert payload["request_line"] == f"{GET} {redirect_target} HTTP/1.1"
    assert len(response.history) == 1
    assert response.history[0].url == target_url
    assert _request_lines(async_http_proxy.requests) == (
        f"{GET} {target_url} HTTP/1.1",
        f"{GET} {redirect_target} HTTP/1.1",
    )


# An explicit-proxy http -> https redirect now upgrades to a CONNECT tunnel; the
# CONNECT path itself is covered by test_https_proxy_connect.py and the Rust unit
# test explicit_proxy_tunnels_https_redirect_via_connect.


def test_proxy_connection_failure_cleans_up_request_stats(unused_tcp_port: int) -> None:
    target_url = "http://example.test/proxy-connection-failure"

    with foghttp.Client(proxy=f"http://127.0.0.1:{unused_tcp_port}") as client:
        with pytest.raises(foghttp.RequestError):
            client.get(target_url)

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0


def test_proxy_protocol_failure_cleans_up_request_stats(
    sync_http_proxy: SyncHTTPProxy,
    unused_tcp_port: int,
) -> None:
    target_url = _target_url(unused_tcp_port, "/invalid-proxy-response")

    with foghttp.Client(proxy=sync_http_proxy.base_url) as client:
        with pytest.raises(foghttp.RequestError):
            client.get(target_url)

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0
    assert len(sync_http_proxy.requests) == 1


def _target_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _proxy_redirect_url(port: int, location: str) -> str:
    return _target_url(port, f"{PROXY_REDIRECT_PATH}?location={location}")


def _request_lines(requests: list[ProxyRequest]) -> tuple[str, ...]:
    return tuple(request.request_line for request in requests)


def _basic_proxy_auth(username: str, password: str) -> str:
    token = f"{username}:{password}".encode()
    return f"Basic {b64encode(token).decode('ascii')}"
