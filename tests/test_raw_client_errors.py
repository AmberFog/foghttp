from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.config import ClientConfig
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.options import ClientOptions
from foghttp._client.proxy import ProxyTransportPolicy
from foghttp._client.raw.lifecycle import create_raw_client
from foghttp._client.raw.requests import RawRequestOptions, send_raw_request, send_raw_request_async
from foghttp._request_body import RequestBody
from foghttp.errors import (
    PoolTimeout,
    ReadTimeout,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    TimeoutError,
    WriteTimeout,
)
from foghttp.limits import Limits
from foghttp.methods import GET
from foghttp.timeouts import Timeouts


READ_TIMEOUT_RAW_ARGS = (
    "response body read timeout expired",
    "response_body",
    0.1,
    0.1,
    "https://example.com",
    0,
)

WRITE_TIMEOUT_RAW_ARGS = (
    "request body write timeout expired",
    "request_body",
    0.1,
    0.1,
    "https://example.com",
    0,
)
CONNECTION_ACQUIRE_TIMEOUT_RAW_ARGS = (
    "connection acquire timeout expired",
    "connection_acquire",
    0.1,
    0.1,
    "https://example.com",
    0,
)


INVALID_PHASE_RAW_ARGS = (
    "response body read timeout expired",
    "unknown",
    0.1,
    0.1,
    "https://example.com",
    0,
)
BYTEARRAY_ELAPSED_RAW_ARGS = (
    "response body read timeout expired",
    "response_body",
    bytearray(b"not-a-float"),
    0.1,
    "https://example.com",
    0,
)
BYTEARRAY_REDIRECT_HOP_RAW_ARGS = (
    "response body read timeout expired",
    "response_body",
    0.1,
    0.1,
    "https://example.com",
    bytearray(b"not-an-int"),
)


def _default_client_config() -> ClientConfig:
    return ClientConfig.from_options(
        ClientOptions(
            base_url=None,
            headers=None,
            params=None,
            limits=Limits(),
            timeouts=Timeouts(),
            http_versions=None,
            follow_redirects=False,
            max_redirects=DEFAULT_MAX_REDIRECTS,
            cookies=False,
            trust_env=False,
            proxy=None,
            tls=None,
            runtime="dedicated",
            runtime_workers=1,
            policy_hooks=None,
            telemetry=None,
            lifecycle_debug=None,
        ),
    )


def _raw_request(url: str) -> RawRequestOptions:
    return RawRequestOptions(
        method=GET,
        url=url,
        headers=[],
        body=RequestBody.replayable_body(None),
        use_proxy_transport=False,
        proxy_policy=ProxyTransportPolicy.DIRECT,
        timeouts=Timeouts(),
    )


class TimeoutRawClient:
    def request(self, **_kwargs: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)

    async def request_async(self, **_kwargs: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)


class ReadTimeoutRawClient:
    def request(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(READ_TIMEOUT_RAW_ARGS)

    async def request_async(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(READ_TIMEOUT_RAW_ARGS)


class WriteTimeoutRawClient:
    def request(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpWriteTimeoutError(WRITE_TIMEOUT_RAW_ARGS)

    async def request_async(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpWriteTimeoutError(WRITE_TIMEOUT_RAW_ARGS)


class MalformedReadTimeoutRawClient:
    def __init__(self, raw_args: tuple[object, ...]) -> None:
        self._raw_args = raw_args

    def request(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(self._raw_args)


class PoolTimeoutRawClient:
    def request(self, **_kwargs: object) -> object:
        msg = "request acquire timeout expired"
        raise _foghttp.FogHttpPoolTimeoutError(msg)

    async def request_async(self, **_kwargs: object) -> object:
        msg = "request acquire timeout expired"
        raise _foghttp.FogHttpPoolTimeoutError(msg)


class ConnectionAcquireTimeoutRawClient:
    def request(self, **_kwargs: object) -> object:
        raise _foghttp.FogHttpPoolTimeoutError(CONNECTION_ACQUIRE_TIMEOUT_RAW_ARGS)


class BodyTooLargeRawClient:
    def request(self, **_kwargs: object) -> object:
        msg = "response body exceeded max_response_body_size"
        raise _foghttp.FogHttpResponseBodyTooLargeError(msg)

    async def request_async(self, **_kwargs: object) -> object:
        msg = "response body exceeded max_response_body_size"
        raise _foghttp.FogHttpResponseBodyTooLargeError(msg)


class BodyBudgetExceededRawClient:
    def request(self, **_kwargs: object) -> object:
        msg = "buffered response bodies exceeded max_buffered_response_bytes"
        raise _foghttp.FogHttpResponseBodyBudgetExceededError(msg)

    async def request_async(self, **_kwargs: object) -> object:
        msg = "buffered response bodies exceeded max_buffered_response_bytes"
        raise _foghttp.FogHttpResponseBodyBudgetExceededError(msg)


def test_raw_client_constructor_error_maps_to_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_raw_client(**_kwargs: object) -> object:
        msg = "runtime failed"
        raise _foghttp.FogHttpError(msg)

    monkeypatch.setattr(_foghttp, "RawClient", fail_raw_client)

    with pytest.raises(ValueError, match="runtime failed"):
        create_raw_client(config=_default_client_config())


def test_sync_raw_timeout_maps_to_public_timeout(faker: Faker) -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        send_raw_request(
            raw_client=TimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


async def test_async_raw_timeout_maps_to_public_timeout(faker: Faker) -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        await send_raw_request_async(
            raw_client=TimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


def test_sync_raw_read_timeout_maps_to_public_read_timeout(faker: Faker) -> None:
    with pytest.raises(ReadTimeout, match="response body read timeout expired"):
        send_raw_request(
            raw_client=ReadTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


async def test_async_raw_read_timeout_maps_to_public_read_timeout(faker: Faker) -> None:
    with pytest.raises(ReadTimeout, match="response body read timeout expired"):
        await send_raw_request_async(
            raw_client=ReadTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


def test_sync_raw_write_timeout_maps_to_public_write_timeout(faker: Faker) -> None:
    with pytest.raises(WriteTimeout, match="request body write timeout expired") as exc_info:
        send_raw_request(
            raw_client=WriteTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )

    assert exc_info.value.phase == "request_body"


async def test_async_raw_write_timeout_maps_to_public_write_timeout(faker: Faker) -> None:
    with pytest.raises(WriteTimeout, match="request body write timeout expired") as exc_info:
        await send_raw_request_async(
            raw_client=WriteTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )

    assert exc_info.value.phase == "request_body"


@pytest.mark.parametrize(
    "raw_args",
    [
        INVALID_PHASE_RAW_ARGS,
        BYTEARRAY_ELAPSED_RAW_ARGS,
        BYTEARRAY_REDIRECT_HOP_RAW_ARGS,
    ],
)
def test_malformed_raw_timeout_diagnostic_does_not_escape_mapping(
    faker: Faker,
    raw_args: tuple[object, ...],
) -> None:
    with pytest.raises(ReadTimeout, match="response body read timeout expired") as exc_info:
        send_raw_request(
            raw_client=MalformedReadTimeoutRawClient(raw_args),
            request=_raw_request(faker.url()),
        )

    assert exc_info.value.diagnostic is None


def test_sync_raw_pool_timeout_maps_to_public_pool_timeout(faker: Faker) -> None:
    with pytest.raises(PoolTimeout, match="request acquire timeout expired"):
        send_raw_request(
            raw_client=PoolTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


async def test_async_raw_pool_timeout_maps_to_public_pool_timeout(faker: Faker) -> None:
    with pytest.raises(PoolTimeout, match="request acquire timeout expired"):
        await send_raw_request_async(
            raw_client=PoolTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )


def test_raw_connection_acquire_timeout_preserves_public_diagnostic(faker: Faker) -> None:
    with pytest.raises(PoolTimeout, match="connection acquire timeout expired") as exc_info:
        send_raw_request(
            raw_client=ConnectionAcquireTimeoutRawClient(),
            request=_raw_request(faker.url()),
        )

    assert exc_info.value.phase == "connection_acquire"
    assert exc_info.value.origin == "https://example.com"


def test_sync_raw_body_limit_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyTooLargeError, match="max_response_body_size"):
        send_raw_request(
            raw_client=BodyTooLargeRawClient(),
            request=_raw_request(faker.url()),
        )


async def test_async_raw_body_limit_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyTooLargeError, match="max_response_body_size"):
        await send_raw_request_async(
            raw_client=BodyTooLargeRawClient(),
            request=_raw_request(faker.url()),
        )


def test_sync_raw_body_budget_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyBudgetExceededError, match="max_buffered_response_bytes"):
        send_raw_request(
            raw_client=BodyBudgetExceededRawClient(),
            request=_raw_request(faker.url()),
        )


async def test_async_raw_body_budget_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyBudgetExceededError, match="max_buffered_response_bytes"):
        await send_raw_request_async(
            raw_client=BodyBudgetExceededRawClient(),
            request=_raw_request(faker.url()),
        )
