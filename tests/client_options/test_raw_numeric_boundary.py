from contextlib import closing
import math
from types import SimpleNamespace

from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp.methods import GET
from foghttp.status_codes.success import OK

from .raw_options import raw_client_options


CUSTOM_ONLY_TRUST_WEBPKI_ROOTS = False
REQUEST_BODY_REPLAYABLE = True
BODY_STREAM = None
USE_PROXY_TRANSPORT = False
PROXY_TRANSPORT_POLICY = ProxyTransportPolicy.DIRECT.value
INVALID_REQUEST_CASES = (
    pytest.param({"method": "NOT A METHOD"}, "invalid HTTP method", id="method"),
    pytest.param({"headers": [("bad name", "value")]}, "invalid HTTP header name", id="header-name"),
    pytest.param({"headers": [("x-test", "bad\r\nvalue")]}, "failed to parse header value", id="header-value"),
)


def test_raw_client_rejects_positional_constructor_arguments() -> None:
    with pytest.raises(TypeError, match="positional"):
        _foghttp.RawClient(*raw_client_options().values())


def test_raw_client_rejects_empty_custom_only_tls_trust_store() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="TLS trust store is empty; enable WebPKI roots or provide CA certificates",
    ):
        _foghttp.RawClient(
            **raw_client_options(
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
            **raw_client_options(
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
            **raw_client_options(
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
            **raw_client_options(http_proxy_url="http://user@proxy.example:8080"),
        )


def test_raw_client_rejects_invalid_idle_timeout_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.idle_timeout must be a finite number between 0 and",
    ):
        _foghttp.RawClient(**raw_client_options(idle_timeout=math.nan))


def test_raw_client_rejects_invalid_runtime_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="runtime must be 'shared' or 'dedicated'",
    ):
        _foghttp.RawClient(**raw_client_options(runtime="global"))


def test_raw_client_rejects_runtime_workers_with_shared_runtime_without_panic() -> None:
    with pytest.raises(
        _foghttp.FogHttpError,
        match="runtime_workers requires runtime='dedicated'",
    ):
        _foghttp.RawClient(**raw_client_options(runtime="shared", runtime_workers=1))


def test_raw_client_rejects_too_large_active_request_limit_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_active_requests must be an integer between 0 and",
    ):
        _foghttp.RawClient(**raw_client_options(max_active_requests=2**31))


def test_raw_client_rejects_too_large_connection_limit_without_panic() -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.max_connections must be an integer between 0 and",
    ):
        _foghttp.RawClient(**raw_client_options(max_connections=2**31))


def test_raw_client_accepts_unbounded_connection_limit_without_panic() -> None:
    raw_client = _foghttp.RawClient(**raw_client_options(max_connections=None))
    raw_client.close()


@pytest.mark.parametrize("field_name", ["max_stream_decoded_bytes", "max_stream_decoder_memory_bytes"])
@pytest.mark.parametrize("value", [-1, 2**31, 1.5, True, False, "128"])
def test_raw_client_rejects_invalid_stream_limits(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=rf"Limits\.{field_name} must be an integer between 0 and"):
        _foghttp.RawClient(**raw_client_options(**{field_name: value}))


def test_raw_client_rejects_unbounded_stream_decoder_memory() -> None:
    with pytest.raises(ValueError, match=r"Limits\.max_stream_decoder_memory_bytes must be an integer"):
        _foghttp.RawClient(**raw_client_options(max_stream_decoder_memory_bytes=None))


@pytest.mark.parametrize("decoded_limit", [None, 0, 2**31 - 1])
@pytest.mark.parametrize("memory_limit", [0, 2**31 - 1])
def test_raw_client_accepts_stream_limit_boundaries(decoded_limit: int | None, memory_limit: int) -> None:
    with closing(
        _foghttp.RawClient(
            **raw_client_options(
                max_stream_decoded_bytes=decoded_limit,
                max_stream_decoder_memory_bytes=memory_limit,
            ),
        ),
    ) as raw_client:
        assert raw_client.stats().stream_decoder_reserved_bytes == 0


@pytest.mark.parametrize("request_method", ["request_stream", "request_stream_async"])
@pytest.mark.parametrize("value", [None, 0, 1, "true", b"false", [], object()])
def test_raw_stream_rejects_non_bool_decode_content_before_dispatch(request_method: str, value: object) -> None:
    with closing(_raw_client()) as raw_client:
        with pytest.raises(TypeError):
            getattr(raw_client, request_method)(
                **_raw_request_options(url="https://example.invalid"),
                decode_content=value,
            )
        assert raw_client.stats().total_requests == 0
        assert raw_client.stats().stream_decoder_reserved_bytes == 0


def test_raw_client_rejects_non_callable_policy_hook_without_panic() -> None:
    policy_hooks = SimpleNamespace(
        before_send=object(),
        on_response_headers=None,
        after_response_body=None,
    )

    with pytest.raises(
        TypeError,
        match="before_send transport policy hook must be callable or None",
    ):
        _foghttp.RawClient(**raw_client_options(policy_hooks=policy_hooks))


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


@pytest.mark.parametrize(("overrides", "message"), INVALID_REQUEST_CASES)
@pytest.mark.parametrize("request_method", ["request", "request_stream"])
def test_raw_sync_request_errors_preserve_type_and_release_slot(
    sync_http_server: str,
    request_method: str,
    overrides: dict[str, object],
    message: str,
) -> None:
    with closing(_raw_client()) as raw_client:
        options = _raw_request_options(url=sync_http_server)
        options.update(overrides)
        with pytest.raises(_foghttp.FogHttpError, match=message) as exc_info:
            getattr(raw_client, request_method)(**options)
        assert type(exc_info.value) is _foghttp.FogHttpError
        assert exc_info.value.args == (message,)
        assert raw_client.stats().active_requests == 0
        response = raw_client.request(**_raw_request_options(url=sync_http_server))
        assert response.status_code == OK


@pytest.mark.parametrize(("overrides", "message"), INVALID_REQUEST_CASES)
@pytest.mark.parametrize("request_method", ["request_async", "request_stream_async"])
async def test_raw_async_request_errors_preserve_type_and_release_slot(
    sync_http_server: str,
    request_method: str,
    overrides: dict[str, object],
    message: str,
) -> None:
    with closing(_raw_client()) as raw_client:
        options = _raw_request_options(url=sync_http_server)
        options.update(overrides)
        with pytest.raises(_foghttp.FogHttpError, match=message) as exc_info:
            await getattr(raw_client, request_method)(**options)
        assert type(exc_info.value) is _foghttp.FogHttpError
        assert exc_info.value.args == (message,)
        assert raw_client.stats().active_requests == 0
        response = await raw_client.request_async(**_raw_request_options(url=sync_http_server))
        assert response.status_code == OK


def _raw_client() -> _foghttp.RawClient:
    return _foghttp.RawClient(**raw_client_options())


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
        "auth_override_headers": None,
        "auth_removed_headers": [],
        "extensions": None,
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
