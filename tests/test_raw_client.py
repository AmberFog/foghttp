from base64 import b64encode
from pathlib import Path

from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.config import ClientConfig
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.options import ClientOptions
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp._client.raw.lifecycle import create_raw_client
from foghttp._client.raw.requests import RawRequestOptions, send_raw_request, send_raw_request_async
from foghttp.limits import Limits
from foghttp.methods import GET
from foghttp.timeouts import Timeouts
from foghttp.tls import TLSConfig


RAW_CLIENT_INIT_ARGUMENTS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_idle_connections_per_host",
    "max_pending_requests",
    "max_response_body_size",
    "max_buffered_response_bytes",
    "idle_timeout",
    "keepalive",
    "connect_timeout",
    "follow_redirects",
    "max_redirects",
    "ca_certificates",
    "trust_webpki_roots",
    "runtime_workers",
    "http_proxy_url",
    "http_proxy_authorization",
    "https_proxy_url",
    "https_proxy_authorization",
)

RAW_REQUEST_ARGUMENTS = (
    "method",
    "url",
    "headers",
    "body",
    "body_replayable",
    "use_proxy_transport",
    "proxy_policy",
    "pool_timeout",
    "read_timeout",
    "total_timeout",
)


def _client_config(
    *,
    limits: Limits | None = None,
    timeouts: Timeouts | None = None,
    follow_redirects: bool = False,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    runtime_workers: int | None = None,
    trust_env: bool = False,
    proxy: str | None = None,
    tls: TLSConfig | None = None,
) -> ClientConfig:
    return ClientConfig.from_options(
        ClientOptions(
            base_url=None,
            headers=None,
            params=None,
            limits=limits,
            timeouts=timeouts,
            http_versions=None,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            cookies=False,
            trust_env=trust_env,
            proxy=proxy,
            tls=tls,
            runtime_workers=runtime_workers,
            telemetry=None,
            lifecycle_debug=None,
        ),
    )


def _raw_request(
    *,
    url: str,
    timeouts: Timeouts,
    body: bytes | None = None,
    body_replayable: bool = True,
) -> RawRequestOptions:
    return RawRequestOptions(
        method=GET,
        url=url,
        headers=[],
        body=body,
        body_replayable=body_replayable,
        use_proxy_transport=False,
        proxy_policy=ProxyTransportPolicy.DIRECT,
        timeouts=timeouts,
    )


def test_create_raw_client_passes_transport_limits_to_rust_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_options.update(dict(zip(RAW_CLIENT_INIT_ARGUMENTS, args, strict=True)))

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    limits = Limits(
        max_active_requests=11,
        max_active_requests_per_origin=17,
        max_pending_requests=13,
        max_response_body_size=19,
        max_buffered_response_bytes=23,
        max_idle_connections_per_host=7,
        idle_timeout=5.5,
        keepalive=False,
    )
    timeouts = Timeouts(connect=2.5)
    follow_redirects = True
    max_redirects = 9
    runtime_workers = 3

    raw_client = create_raw_client(
        config=_client_config(
            limits=limits,
            timeouts=timeouts,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            runtime_workers=runtime_workers,
        ),
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options == {
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": limits.max_active_requests_per_origin,
        "max_idle_connections_per_host": limits.max_idle_connections_per_host,
        "max_pending_requests": limits.max_pending_requests,
        "max_response_body_size": limits.max_response_body_size,
        "max_buffered_response_bytes": limits.max_buffered_response_bytes,
        "idle_timeout": limits.idle_timeout,
        "keepalive": limits.keepalive,
        "connect_timeout": timeouts.connect,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "ca_certificates": (),
        "trust_webpki_roots": True,
        "runtime_workers": runtime_workers,
        "http_proxy_url": None,
        "http_proxy_authorization": None,
        "https_proxy_url": None,
        "https_proxy_authorization": None,
    }


def test_create_raw_client_passes_proxy_endpoint_and_auth_to_rust_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_options.update(dict(zip(RAW_CLIENT_INIT_ARGUMENTS, args, strict=True)))

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    username = faker.user_name()
    password = faker.pystr(min_chars=8, max_chars=8)

    raw_client = create_raw_client(
        config=_client_config(proxy=f"http://{username}:{password}@proxy.example:8080"),
    )

    assert isinstance(raw_client, RawClientProbe)
    expected_auth = _basic_proxy_auth(username, password)
    assert captured_options["http_proxy_url"] == "http://proxy.example:8080"
    assert captured_options["http_proxy_authorization"] == expected_auth
    assert captured_options["https_proxy_url"] == "http://proxy.example:8080"
    assert captured_options["https_proxy_authorization"] == expected_auth


def test_create_raw_client_passes_tls_trust_boundary_to_rust_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_options.update(dict(zip(RAW_CLIENT_INIT_ARGUMENTS, args, strict=True)))

    ca_body = faker.binary(length=16)
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca_body)
    tls = TLSConfig(ca_certificates=(ca_path,), trust_webpki_roots=False)
    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(
        config=_client_config(tls=tls),
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options["ca_certificates"] == (ca_body,)
    assert captured_options["trust_webpki_roots"] is False


def test_send_raw_request_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        def request(self, *args: object) -> object:
            captured_options.update(dict(zip(RAW_REQUEST_ARGUMENTS, args, strict=True)))
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, total=5.5)
    url = faker.url()
    body = faker.binary(length=8)
    body_replayable = False

    response = send_raw_request(
        raw_client=RawClientProbe(),
        request=_raw_request(
            url=url,
            body=body,
            body_replayable=body_replayable,
            timeouts=timeouts,
        ),
    )

    assert response is raw_response
    assert captured_options == {
        "method": GET,
        "url": url,
        "headers": [],
        "body": body,
        "body_replayable": body_replayable,
        "use_proxy_transport": False,
        "proxy_policy": ProxyTransportPolicy.DIRECT.value,
        "pool_timeout": timeouts.pool,
        "read_timeout": timeouts.read,
        "total_timeout": timeouts.total,
    }


async def test_send_raw_request_async_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        async def request_async(self, *args: object) -> object:
            captured_options.update(dict(zip(RAW_REQUEST_ARGUMENTS, args, strict=True)))
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, total=5.5)
    url = faker.url()

    response = await send_raw_request_async(
        raw_client=RawClientProbe(),
        request=_raw_request(url=url, timeouts=timeouts),
    )

    assert response is raw_response
    assert captured_options == {
        "method": GET,
        "url": url,
        "headers": [],
        "body": None,
        "body_replayable": True,
        "use_proxy_transport": False,
        "proxy_policy": ProxyTransportPolicy.DIRECT.value,
        "pool_timeout": timeouts.pool,
        "read_timeout": timeouts.read,
        "total_timeout": timeouts.total,
    }


def _basic_proxy_auth(username: str, password: str) -> str:
    token = f"{username}:{password}".encode()
    return f"Basic {b64encode(token).decode('ascii')}"
