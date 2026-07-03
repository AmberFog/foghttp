import math

from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp.methods import GET


KEEPALIVE = True
FOLLOW_REDIRECTS = False
TRUST_WEBPKI_ROOTS = True
CUSTOM_ONLY_TRUST_WEBPKI_ROOTS = False
REQUEST_BODY_REPLAYABLE = True
BODY_STREAM = None
USE_PROXY_TRANSPORT = False
PROXY_TRANSPORT_POLICY = ProxyTransportPolicy.DIRECT.value


def test_raw_client_rejects_positional_constructor_arguments() -> None:
    with pytest.raises(TypeError, match="positional"):
        _foghttp.RawClient(*_raw_client_options().values())


def test_raw_client_rejects_empty_custom_only_tls_trust_store() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="TLS trust store is empty; enable WebPKI roots or provide CA certificates",
    ):
        _foghttp.RawClient(
            **_raw_client_options(
                ca_certificates=(),
                trust_webpki_roots=CUSTOM_ONLY_TRUST_WEBPKI_ROOTS,
            ),
        )


@pytest.mark.parametrize(
    ("http_proxy_url", "https_proxy_url"),
    [
        pytest.param("https://proxy.example:443", None, id="http-proxy-slot"),
        pytest.param(None, "https://proxy.example:443", id="https-proxy-slot"),
    ],
)
def test_raw_client_rejects_https_scheme_proxy_endpoint_without_panic(
    http_proxy_url: str | None,
    https_proxy_url: str | None,
) -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="proxy URL scheme must be http",
    ):
        _foghttp.RawClient(
            **_raw_client_options(
                http_proxy_url=http_proxy_url,
                https_proxy_url=https_proxy_url,
            ),
        )


def test_raw_client_rejects_invalid_https_proxy_authorization_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="proxy authorization header is invalid",
    ):
        _foghttp.RawClient(
            **_raw_client_options(
                https_proxy_url="http://proxy.example:8080",
                https_proxy_authorization="Basic ok\r\nInjected: yes",
            ),
        )


def test_raw_client_rejects_proxy_endpoint_userinfo_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="proxy URL must not include userinfo",
    ):
        _foghttp.RawClient(
            **_raw_client_options(http_proxy_url="http://user@proxy.example:8080"),
        )


def test_raw_client_rejects_invalid_idle_timeout_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.idle_timeout must be a finite number between 0 and",
    ):
        _foghttp.RawClient(**_raw_client_options(idle_timeout=math.nan))


def test_raw_client_rejects_invalid_runtime_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="runtime must be 'shared' or 'dedicated'",
    ):
        _foghttp.RawClient(**_raw_client_options(runtime="global"))


def test_raw_client_rejects_runtime_workers_with_shared_runtime_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="runtime_workers requires runtime='dedicated'",
    ):
        _foghttp.RawClient(**_raw_client_options(runtime="shared", runtime_workers=1))


def test_raw_client_rejects_too_large_active_request_limit_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_active_requests must be an integer between 0 and",
    ):
        _foghttp.RawClient(**_raw_client_options(max_active_requests=2**31))


def test_raw_client_rejects_too_large_connection_limit_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_connections must be an integer between 0 and",
    ):
        _foghttp.RawClient(**_raw_client_options(max_connections=2**31))


def test_raw_client_accepts_unbounded_connection_limit_without_panic() -> None:
    raw_client = _foghttp.RawClient(**_raw_client_options(max_connections=None))
    raw_client.close()


def test_raw_client_sync_request_rejects_positional_arguments(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(TypeError, match="positional"):
            raw_client.request(*_raw_request_options(url=faker.url()).values())
    finally:
        raw_client.close()


def test_raw_client_async_request_rejects_positional_arguments(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(TypeError, match="positional"):
            raw_client.request_async(*_raw_request_options(url=faker.url()).values())
    finally:
        raw_client.close()


def test_raw_client_sync_stream_request_rejects_positional_arguments(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(TypeError, match="positional"):
            raw_client.request_stream(*_raw_request_options(url=faker.url()).values())
    finally:
        raw_client.close()


def test_raw_client_async_stream_request_rejects_positional_arguments(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(TypeError, match="positional"):
            raw_client.request_stream_async(*_raw_request_options(url=faker.url()).values())
    finally:
        raw_client.close()


def test_raw_client_sync_request_rejects_invalid_timeout_without_panic(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.pool must be a finite number between 0 and",
        ):
            raw_client.request(**_raw_request_options(url=faker.url(), pool_timeout=math.nan))
    finally:
        raw_client.close()


def test_raw_client_sync_request_rejects_invalid_read_timeout_without_panic(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.read must be a finite number between 0 and",
        ):
            raw_client.request(**_raw_request_options(url=faker.url(), read_timeout=math.nan))
    finally:
        raw_client.close()


def test_raw_client_sync_request_rejects_invalid_write_timeout_without_panic(faker: Faker) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.write must be a finite number between 0 and",
        ):
            raw_client.request(**_raw_request_options(url=faker.url(), write_timeout=math.nan))
    finally:
        raw_client.close()


async def test_raw_client_async_request_rejects_invalid_timeout_without_panic(
    faker: Faker,
) -> None:
    raw_client = _raw_client()
    try:
        with pytest.raises(
            ValueError,
            match=r"Timeouts\.total must be a finite number between 0 and",
        ):
            raw_client.request_async(**_raw_request_options(url=faker.url(), total_timeout=math.inf))
    finally:
        raw_client.close()


def _raw_client() -> _foghttp.RawClient:
    return _foghttp.RawClient(**_raw_client_options())


def _raw_client_options(**overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "max_active_requests": 1,
        "max_active_requests_per_origin": None,
        "max_connections": 1,
        "max_connections_per_host": None,
        "max_idle_connections_per_host": 1,
        "max_pending_requests": 1,
        "max_response_body_size": None,
        "max_buffered_response_bytes": None,
        "idle_timeout": 30.0,
        "keepalive": KEEPALIVE,
        "connect_timeout": 2.0,
        "follow_redirects": FOLLOW_REDIRECTS,
        "max_redirects": 20,
        "ca_certificates": (),
        "trust_webpki_roots": TRUST_WEBPKI_ROOTS,
        "runtime": "dedicated",
        "runtime_workers": None,
        "http_proxy_url": None,
        "http_proxy_authorization": None,
        "https_proxy_url": None,
        "https_proxy_authorization": None,
    }
    options.update(overrides)
    return options


def _raw_request_options(
    *,
    url: str,
    pool_timeout: float = 1.0,
    read_timeout: float = 1.0,
    write_timeout: float = 1.0,
    total_timeout: float = 1.0,
) -> dict[str, object]:
    return {
        "method": GET,
        "url": url,
        "headers": [],
        "body": None,
        "body_stream": BODY_STREAM,
        "body_replayable": REQUEST_BODY_REPLAYABLE,
        "use_proxy_transport": USE_PROXY_TRANSPORT,
        "proxy_policy": PROXY_TRANSPORT_POLICY,
        "pool_timeout": pool_timeout,
        "read_timeout": read_timeout,
        "write_timeout": write_timeout,
        "total_timeout": total_timeout,
    }
