from base64 import b64encode
from urllib.parse import urlsplit

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, POST
from tests.client_proxy.environment import clear_proxy_environment
from tests.client_proxy.http_proxy_server import AsyncHTTPProxy, SyncHTTPProxy


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


def _basic_proxy_auth(username: str, password: str) -> str:
    token = f"{username}:{password}".encode()
    return f"Basic {b64encode(token).decode('ascii')}"
