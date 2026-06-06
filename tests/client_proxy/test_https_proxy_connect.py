import asyncio
from base64 import b64encode
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK
from foghttp.timeouts import Timeouts
from foghttp.tls import TLSConfig
from tests.client_proxy.connect_proxy_server import ConnectProxy, start_connect_proxy
from tests.client_proxy.environment import clear_proxy_environment
from tests.client_proxy.http_proxy_server import SyncHTTPProxy
from tests.client_tls.certificates import TLSCertificateBundle, create_tls_certificate_bundle
from tests.client_tls.constants import TLS_OK_BODY, TLS_PATH
from tests.client_tls.models import TLSServer
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats


def _target_url(server: TLSServer) -> str:
    return f"{server.url}{TLS_PATH}"


def _tls(bundle: TLSCertificateBundle) -> TLSConfig:
    return TLSConfig(ca_certificates=(str(bundle.ca_path),))


def _basic(username: str, password: str) -> str:
    token = b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


@contextmanager
def _connect_proxy(
    *,
    require_auth: bool = False,
    expected_authorization: str | None = None,
    reject_status: int | None = None,
    reject_body: bytes = b"",
    early_close: bool = False,
    http_redirect_location: str | None = None,
    hang: bool = False,
) -> Iterator[ConnectProxy]:
    proxy = start_connect_proxy(
        require_auth=require_auth,
        expected_authorization=expected_authorization,
        reject_status=reject_status,
        reject_body=reject_body,
        early_close=early_close,
        http_redirect_location=http_redirect_location,
        hang=hang,
    )
    try:
        yield proxy
    finally:
        proxy.close()


def test_sync_https_request_tunnels_through_connect_proxy(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    with foghttp.Client(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        response = client.get(url)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY
    assert response.request.url == url
    connects = connect_proxy.connects
    assert len(connects) == 1
    assert connects[0].authority == urlsplit(server.url).netloc


async def test_async_https_request_tunnels_through_connect_proxy(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    async with foghttp.AsyncClient(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        response = await client.get(url)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY
    assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc


def test_sync_https_stream_tunnels_through_connect_proxy(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    with foghttp.Client(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        with client.stream(GET, url) as response:
            content = b"".join(response.iter_bytes())

        stats = client.stats()

    assert response.status_code == OK
    assert content == TLS_OK_BODY
    assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc
    assert stats.active_requests == 0
    assert stats.response_body_closed == 1
    assert stats.response_body_aborted == 0


async def test_async_https_stream_tunnels_through_connect_proxy(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    async with foghttp.AsyncClient(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        async with client.stream(GET, url) as response:
            chunks = [chunk async for chunk in response.aiter_bytes()]

        stats = client.stats()

    assert response.status_code == OK
    assert b"".join(chunks) == TLS_OK_BODY
    assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc
    assert stats.active_requests == 0
    assert stats.response_body_closed == 1
    assert stats.response_body_aborted == 0


def test_sync_https_stream_early_close_releases_slot(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    with foghttp.Client(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        with client.stream(GET, url) as response:
            assert response.status_code == OK
            assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc
            wait_for_sync_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="CONNECT stream should keep the request slot before body close",
            )

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="closing a CONNECT stream before body EOF must release the request slot",
        )


async def test_async_https_stream_early_close_releases_slot(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    url = _target_url(server)

    async with foghttp.AsyncClient(proxy=connect_proxy.base_url, tls=_tls(bundle)) as client:
        async with client.stream(GET, url) as response:
            assert response.status_code == OK
            assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="CONNECT stream should keep the request slot before body close",
            )

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="closing a CONNECT stream before body EOF must release the request slot",
        )


def test_proxy_authorization_is_sent_only_on_connect_and_redacted(
    faker: Faker,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    username = faker.user_name()
    password = faker.pystr(min_chars=10, max_chars=10)
    expected = _basic(username, password)
    with _connect_proxy(require_auth=True, expected_authorization=expected) as proxy:
        proxy_url = f"http://{username}:{password}@{urlsplit(proxy.base_url).netloc}"
        with foghttp.Client(proxy=proxy_url, tls=_tls(bundle)) as client:
            response = client.get(_target_url(server))

        assert response.content == TLS_OK_BODY
        connect = proxy.connects[0]
        assert connect.proxy_authorization == expected
        # Proxy credentials authenticate the CONNECT request only and must never
        # appear on the tunnelled request to the target or in diagnostics.
        assert "proxy-authorization" not in response.request.headers
        assert username not in repr(response.request)
        assert password not in repr(response.request)


def test_sync_http_to_https_redirect_uses_connect_tunnel(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    redirect_target = _target_url(server)
    with _connect_proxy(http_redirect_location=redirect_target) as proxy:
        with foghttp.Client(
            proxy=proxy.base_url,
            tls=_tls(bundle),
            follow_redirects=True,
        ) as client:
            response = client.get("http://proxy-start.example/redirect")

        assert response.status_code == OK
        assert response.content == TLS_OK_BODY
        assert response.url == redirect_target
        assert len(response.history) == 1
        assert proxy.connects[0].authority == urlsplit(server.url).netloc


async def test_async_http_to_https_redirect_uses_connect_tunnel(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    redirect_target = _target_url(server)
    with _connect_proxy(http_redirect_location=redirect_target) as proxy:
        async with foghttp.AsyncClient(
            proxy=proxy.base_url,
            tls=_tls(bundle),
            follow_redirects=True,
        ) as client:
            response = await client.get("http://proxy-start.example/redirect")

        assert response.status_code == OK
        assert response.content == TLS_OK_BODY
        assert response.url == redirect_target
        assert len(response.history) == 1
        assert proxy.connects[0].authority == urlsplit(server.url).netloc


def test_tunnel_validates_target_certificate(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
    tmp_path: Path,
) -> None:
    server, _bundle = tls_target
    unrelated_directory = tmp_path / "unrelated"
    unrelated_directory.mkdir()
    unrelated = create_tls_certificate_bundle(unrelated_directory)

    with foghttp.Client(proxy=connect_proxy.base_url, tls=_tls(unrelated)) as client:
        with pytest.raises(foghttp.RequestError):
            client.get(_target_url(server))

        stats = client.stats()

    assert stats.failed_requests == 1
    assert stats.active_requests == 0


def test_connect_auth_failure_is_request_error(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(require_auth=True, expected_authorization=_basic("user", "secret")) as proxy:
        with foghttp.Client(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError, match="407"):
                client.get(_target_url(server))

            stats = client.stats()

        assert stats.active_requests == 0


def test_connect_non_2xx_is_request_error(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(reject_status=502) as proxy:
        with foghttp.Client(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError, match="502"):
                client.get(_target_url(server))

            stats = client.stats()

        assert stats.active_requests == 0


def test_connect_non_2xx_with_body_preserves_status_error(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(reject_status=502, reject_body=b"proxy error body") as proxy:
        with foghttp.Client(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError, match="502"):
                client.get(_target_url(server))

            stats = client.stats()

        assert stats.active_requests == 0


async def test_async_connect_non_2xx_is_request_error(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(reject_status=502) as proxy:
        async with foghttp.AsyncClient(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError, match="502"):
                await client.get(_target_url(server))

            stats = client.stats()

        assert stats.active_requests == 0


def test_early_tunnel_close_is_request_error_and_releases_slot(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(early_close=True) as proxy:
        with foghttp.Client(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError):
                client.get(_target_url(server))

            stats = client.stats()

        assert stats.failed_requests == 1
        assert stats.active_requests == 0


async def test_async_early_tunnel_close_releases_slot(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(early_close=True) as proxy:
        async with foghttp.AsyncClient(proxy=proxy.base_url, tls=_tls(bundle)) as client:
            with pytest.raises(foghttp.RequestError):
                await client.get(_target_url(server))

            stats = client.stats()

        assert stats.failed_requests == 1
        assert stats.active_requests == 0


@pytest.mark.parametrize(
    "proxy_env_name",
    [
        pytest.param("HTTPS_PROXY", id="https-proxy"),
        pytest.param("ALL_PROXY", id="all-proxy"),
    ],
)
def test_trust_env_https_target_tunnels_via_connect(
    proxy_env_name: str,
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bundle = tls_target
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv(proxy_env_name, connect_proxy.base_url)

    with foghttp.Client(trust_env=True, tls=_tls(bundle)) as client:
        response = client.get(_target_url(server))

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY
    assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc


async def test_async_trust_env_https_target_tunnels_via_connect(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bundle = tls_target
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", connect_proxy.base_url)

    async with foghttp.AsyncClient(trust_env=True, tls=_tls(bundle)) as client:
        response = await client.get(_target_url(server))

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY
    assert connect_proxy.connects[0].authority == urlsplit(server.url).netloc


def test_trust_env_no_proxy_bypasses_connect_for_https_target(
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, bundle = tls_target
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", connect_proxy.base_url)
    monkeypatch.setenv("NO_PROXY", urlsplit(server.url).hostname or "")

    with foghttp.Client(trust_env=True, tls=_tls(bundle)) as client:
        response = client.get(_target_url(server))

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY
    # NO_PROXY must take the HTTPS target direct, never through the CONNECT proxy.
    assert connect_proxy.connects == []


def test_failed_connect_does_not_leak_proxy_credentials(
    faker: Faker,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    username = faker.user_name()
    password = faker.pystr(min_chars=10, max_chars=10)
    with _connect_proxy(
        require_auth=True,
        expected_authorization=_basic("expected-user", "expected-secret"),
    ) as proxy:
        proxy_url = f"http://{username}:{password}@{urlsplit(proxy.base_url).netloc}"
        with (
            foghttp.Client(proxy=proxy_url, tls=_tls(bundle)) as client,
            pytest.raises(foghttp.RequestError) as exc_info,
        ):
            client.get(_target_url(server))

    # The CONNECT failure surfaces a redacted, diagnostic error: the proxy status
    # is visible but the proxy credentials sent on the CONNECT request are not.
    message = str(exc_info.value)
    assert "407" in message
    assert username not in message
    assert password not in message


def test_connect_handshake_timeout_is_request_error_and_releases_slot(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(hang=True) as proxy:
        with foghttp.Client(
            proxy=proxy.base_url,
            tls=_tls(bundle),
            timeouts=Timeouts(connect=0.3),
        ) as client:
            with pytest.raises(foghttp.RequestError, match="timed out"):
                client.get(_target_url(server))

            stats = client.stats()

        assert stats.failed_requests == 1
        assert stats.active_requests == 0


async def test_async_cancellation_during_connect_releases_slot(
    tls_target: tuple[TLSServer, TLSCertificateBundle],
) -> None:
    server, bundle = tls_target
    with _connect_proxy(hang=True) as proxy:
        async with foghttp.AsyncClient(
            proxy=proxy.base_url,
            tls=_tls(bundle),
            timeouts=Timeouts(connect=30.0),
        ) as client:
            request = asyncio.create_task(client.get(_target_url(server)))
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 1,
                message="the proxied request should acquire a slot while CONNECT is in flight",
            )

            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0,
                message="cancelling during CONNECT must release the request slot",
            )


def test_per_scheme_environment_proxies_route_independently(
    sync_http_proxy: SyncHTTPProxy,
    connect_proxy: ConnectProxy,
    tls_target: tuple[TLSServer, TLSCertificateBundle],
    monkeypatch: pytest.MonkeyPatch,
    unused_tcp_port: int,
) -> None:
    server, bundle = tls_target
    clear_proxy_environment(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", sync_http_proxy.base_url)
    monkeypatch.setenv("HTTPS_PROXY", connect_proxy.base_url)
    http_target = f"http://target.example:{unused_tcp_port}/via-http-proxy"

    with foghttp.Client(trust_env=True, tls=_tls(bundle)) as client:
        http_response = client.get(http_target)
        https_response = client.get(_target_url(server))

    # Plain HTTP went through HTTP_PROXY in absolute-form; HTTPS tunnelled through
    # the distinct HTTPS_PROXY via CONNECT. One client, two independent routes.
    assert http_response.json()["request_line"] == f"GET {http_target} HTTP/1.1"
    assert [record.request_line for record in sync_http_proxy.requests] == [
        f"GET {http_target} HTTP/1.1",
    ]
    assert https_response.content == TLS_OK_BODY
    assert [connect.authority for connect in connect_proxy.connects] == [
        urlsplit(server.url).netloc,
    ]
