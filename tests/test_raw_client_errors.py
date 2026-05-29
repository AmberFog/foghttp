from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.config import ClientConfig
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.options import ClientOptions
from foghttp._client.raw.lifecycle import create_raw_client
from foghttp._client.raw.requests import RawRequestOptions, send_raw_request, send_raw_request_async
from foghttp.errors import (
    PoolTimeout,
    ReadTimeout,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    TimeoutError,
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
            tls=None,
            runtime_workers=1,
            telemetry=None,
            lifecycle_debug=None,
        ),
    )


def _raw_request(url: str) -> RawRequestOptions:
    return RawRequestOptions(
        method=GET,
        url=url,
        headers=[],
        body=None,
        body_replayable=True,
        timeouts=Timeouts(),
    )


class TimeoutRawClient:
    def request(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)


class ReadTimeoutRawClient:
    def request(self, *_args: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(READ_TIMEOUT_RAW_ARGS)

    async def request_async(self, *_args: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(READ_TIMEOUT_RAW_ARGS)


class MalformedReadTimeoutRawClient:
    def __init__(self, raw_args: tuple[object, ...]) -> None:
        self._raw_args = raw_args

    def request(self, *_args: object) -> object:
        raise _foghttp.FogHttpReadTimeoutError(self._raw_args)


class PoolTimeoutRawClient:
    def request(self, *_args: object) -> object:
        msg = "request acquire timeout expired"
        raise _foghttp.FogHttpPoolTimeoutError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "request acquire timeout expired"
        raise _foghttp.FogHttpPoolTimeoutError(msg)


class BodyTooLargeRawClient:
    def request(self, *_args: object) -> object:
        msg = "response body exceeded max_response_body_size"
        raise _foghttp.FogHttpResponseBodyTooLargeError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "response body exceeded max_response_body_size"
        raise _foghttp.FogHttpResponseBodyTooLargeError(msg)


class BodyBudgetExceededRawClient:
    def request(self, *_args: object) -> object:
        msg = "buffered response bodies exceeded max_buffered_response_bytes"
        raise _foghttp.FogHttpResponseBodyBudgetExceededError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "buffered response bodies exceeded max_buffered_response_bytes"
        raise _foghttp.FogHttpResponseBodyBudgetExceededError(msg)


def test_raw_client_constructor_error_maps_to_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_raw_client(*_args: object) -> object:
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
