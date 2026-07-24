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
from foghttp._client.raw.requests import (
    RawRequestOptions,
    send_raw_request,
    send_raw_request_async,
    send_raw_stream_request,
    send_raw_stream_request_async,
)
from foghttp._client.runtime.constants import RUNTIME_WORKERS_ENV
from foghttp._request_body import RequestBody
from foghttp.limits import Limits
from foghttp.methods import GET
from foghttp.policy import TransportPolicyHooks, TransportPolicyRequest
from foghttp.request_extensions import RequestExtensions
from foghttp.timeouts import Timeouts
from foghttp.tls import TLSConfig


RAW_CLIENT_INIT_ARGUMENTS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_connections",
    "max_connections_per_host",
    "max_idle_connections_per_host",
    "max_pending_requests",
    "max_response_body_size",
    "max_buffered_response_bytes",
    "idle_timeout",
    "keepalive",
    "connect_timeout",
    "follow_redirects",
    "max_redirects",
    "cookies_enabled",
    "ca_certificates",
    "trust_webpki_roots",
    "runtime",
    "runtime_workers",
    "http_proxy_url",
    "http_proxy_authorization",
    "https_proxy_url",
    "https_proxy_authorization",
    "auth_basic_authorization",
    "auth_hook",
    "policy_hooks",
    "retry_retries",
    "retry_backoff",
    "retry_jitter",
    "retry_statuses",
    "retry_methods",
    "retry_network_errors",
    "ssrf_allowed_schemes",
    "ssrf_allowed_origins",
    "ssrf_allowed_domains",
)

RAW_REQUEST_ARGUMENTS = (
    "method",
    "url",
    "headers",
    "auth_override_headers",
    "auth_removed_headers",
    "extensions",
    "body",
    "body_stream",
    "body_replayable",
    "use_proxy_transport",
    "proxy_policy",
    "pool_timeout",
    "read_timeout",
    "write_timeout",
    "total_timeout",
)


def _client_config(
    *,
    limits: Limits | None = None,
    timeouts: Timeouts | None = None,
    follow_redirects: bool = False,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    runtime: str | None = None,
    runtime_workers: int | None = None,
    trust_env: bool = False,
    proxy: str | None = None,
    tls: TLSConfig | None = None,
    policy_hooks: TransportPolicyHooks | None = None,
    cookies: bool = False,
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
            cookies=cookies,
            trust_env=trust_env,
            proxy=proxy,
            tls=tls,
            runtime=runtime,
            runtime_workers=runtime_workers,
            policy_hooks=policy_hooks,
            retry=None,
            ssrf=None,
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
    extensions: RequestExtensions | None = None,
) -> RawRequestOptions:
    return RawRequestOptions(
        method=GET,
        url=url,
        headers=[],
        body=RequestBody(content=body, stream=None, content_length=None, replayable=body_replayable),
        use_proxy_transport=False,
        proxy_policy=ProxyTransportPolicy.DIRECT,
        timeouts=timeouts,
        extensions=extensions,
    )


def test_create_raw_client_passes_transport_limits_to_rust_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    limits = Limits(
        max_active_requests=11,
        max_active_requests_per_origin=17,
        max_connections=29,
        max_connections_per_host=31,
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
            cookies=True,
            runtime_workers=runtime_workers,
        ),
    )

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    assert captured_options == {
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": limits.max_active_requests_per_origin,
        "max_connections": limits.max_connections,
        "max_connections_per_host": limits.max_connections_per_host,
        "max_idle_connections_per_host": limits.max_idle_connections_per_host,
        "max_pending_requests": limits.max_pending_requests,
        "max_response_body_size": limits.max_response_body_size,
        "max_buffered_response_bytes": limits.max_buffered_response_bytes,
        "idle_timeout": limits.idle_timeout,
        "keepalive": limits.keepalive,
        "connect_timeout": timeouts.connect,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "cookies_enabled": True,
        "ca_certificates": (),
        "trust_webpki_roots": True,
        "runtime": "dedicated",
        "runtime_workers": runtime_workers,
        "http_proxy_url": None,
        "http_proxy_authorization": None,
        "https_proxy_url": None,
        "https_proxy_authorization": None,
        "auth_basic_authorization": None,
        "auth_hook": None,
        "policy_hooks": None,
        "retry_retries": None,
        "retry_backoff": 0.0,
        "retry_jitter": 0.0,
        "retry_statuses": [],
        "retry_methods": [],
        "retry_network_errors": False,
        "ssrf_allowed_schemes": None,
        "ssrf_allowed_origins": [],
        "ssrf_allowed_domains": [],
    }


def test_create_raw_client_passes_proxy_endpoint_and_auth_to_rust_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    username = faker.user_name()
    password = faker.pystr(min_chars=8, max_chars=8)

    raw_client = create_raw_client(
        config=_client_config(proxy=f"http://{username}:{password}@proxy.example:8080"),
    )

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    expected_auth = _basic_proxy_auth(username, password)
    assert captured_options["http_proxy_url"] == "http://proxy.example:8080"
    assert captured_options["http_proxy_authorization"] == expected_auth
    assert captured_options["https_proxy_url"] == "http://proxy.example:8080"
    assert captured_options["https_proxy_authorization"] == expected_auth


def test_client_config_normalizes_empty_policy_hooks() -> None:
    assert _client_config(policy_hooks=TransportPolicyHooks()).policy_hooks is None


def test_create_raw_client_passes_enabled_policy_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    def before_send(request: TransportPolicyRequest) -> None:
        del request

    hooks = TransportPolicyHooks(before_send=before_send)
    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(config=_client_config(policy_hooks=hooks))

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options["policy_hooks"] is hooks


def test_create_raw_client_passes_tls_trust_boundary_to_rust_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    ca_body = faker.binary(length=16)
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca_body)
    tls = TLSConfig(ca_certificates=(ca_path,), trust_webpki_roots=False)
    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(
        config=_client_config(tls=tls),
    )

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    assert captured_options["ca_certificates"] == (ca_body,)
    assert captured_options["trust_webpki_roots"] is False


def test_create_raw_client_uses_shared_runtime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(config=_client_config())

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    assert captured_options["runtime"] == "shared"
    assert captured_options["runtime_workers"] is None


def test_create_raw_client_accepts_dedicated_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(config=_client_config(runtime="dedicated"))

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    assert captured_options["runtime"] == "dedicated"
    assert captured_options["runtime_workers"] is None


def test_create_raw_client_uses_dedicated_runtime_when_env_workers_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, **kwargs: object) -> None:
            captured_options.update(kwargs)

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    monkeypatch.setenv(RUNTIME_WORKERS_ENV, "1")

    raw_client = create_raw_client(config=_client_config())

    assert isinstance(raw_client, RawClientProbe)
    _assert_raw_client_argument_names(captured_options)
    assert captured_options["runtime"] == "dedicated"
    assert captured_options["runtime_workers"] is None


def test_send_raw_request_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        def request(self, **kwargs: object) -> object:
            captured_options.update(kwargs)
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, write=5.5, total=6.5)
    url = faker.url()
    body = faker.binary(length=8)
    body_replayable = False
    extensions = RequestExtensions({"tests.request_id": faker.uuid4()})

    response = send_raw_request(
        raw_client=RawClientProbe(),
        request=_raw_request(
            url=url,
            body=body,
            body_replayable=body_replayable,
            extensions=extensions,
            timeouts=timeouts,
        ),
    )

    assert response is raw_response
    assert captured_options == _expected_raw_request_options(
        url=url,
        body=body,
        body_replayable=body_replayable,
        extensions=extensions,
        timeouts=timeouts,
    )


async def test_send_raw_request_async_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        async def request_async(self, **kwargs: object) -> object:
            captured_options.update(kwargs)
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, write=5.5, total=6.5)
    url = faker.url()

    response = await send_raw_request_async(
        raw_client=RawClientProbe(),
        request=_raw_request(url=url, timeouts=timeouts),
    )

    assert response is raw_response
    assert captured_options == _expected_raw_request_options(
        url=url,
        body=None,
        body_replayable=True,
        timeouts=timeouts,
    )


def test_send_raw_stream_request_passes_named_request_options(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        def request_stream(self, **kwargs: object) -> object:
            captured_options.update(kwargs)
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, write=5.5, total=6.5)
    url = faker.url()

    response = send_raw_stream_request(
        raw_client=RawClientProbe(),
        request=_raw_request(url=url, timeouts=timeouts),
    )

    assert response is raw_response
    assert captured_options == _expected_raw_request_options(
        url=url,
        body=None,
        body_replayable=True,
        timeouts=timeouts,
    )


async def test_send_raw_stream_request_async_passes_named_request_options(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        async def request_stream_async(self, **kwargs: object) -> object:
            captured_options.update(kwargs)
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, write=5.5, total=6.5)
    url = faker.url()

    response = await send_raw_stream_request_async(
        raw_client=RawClientProbe(),
        request=_raw_request(url=url, timeouts=timeouts),
    )

    assert response is raw_response
    assert captured_options == _expected_raw_request_options(
        url=url,
        body=None,
        body_replayable=True,
        timeouts=timeouts,
    )


def _basic_proxy_auth(username: str, password: str) -> str:
    token = f"{username}:{password}".encode()
    return f"Basic {b64encode(token).decode('ascii')}"


def _assert_raw_client_argument_names(options: dict[str, object]) -> None:
    assert set(options) == set(RAW_CLIENT_INIT_ARGUMENTS)


def _expected_raw_request_options(
    *,
    url: str,
    body: bytes | None,
    body_replayable: bool,
    timeouts: Timeouts,
    extensions: RequestExtensions | None = None,
) -> dict[str, object]:
    options: dict[str, object] = {
        "method": GET,
        "url": url,
        "headers": [],
        "auth_override_headers": None,
        "auth_removed_headers": (),
        "extensions": extensions,
        "body": body,
        "body_stream": None,
        "body_replayable": body_replayable,
        "use_proxy_transport": False,
        "proxy_policy": ProxyTransportPolicy.DIRECT.value,
        "pool_timeout": timeouts.pool,
        "read_timeout": timeouts.read,
        "write_timeout": timeouts.write,
        "total_timeout": timeouts.total,
    }
    assert set(options) == set(RAW_REQUEST_ARGUMENTS)
    return options
