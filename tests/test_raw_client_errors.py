from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.raw import create_raw_client, send_raw_request, send_raw_request_async
from foghttp.errors import PoolTimeout, ResponseBodyTooLargeError, TimeoutError
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


class TimeoutRawClient:
    def request(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)


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


def test_raw_client_constructor_error_maps_to_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_raw_client(*_args: object) -> object:
        msg = "runtime failed"
        raise _foghttp.FogHttpError(msg)

    monkeypatch.setattr(_foghttp, "RawClient", fail_raw_client)

    with pytest.raises(ValueError, match="runtime failed"):
        create_raw_client(
            limits=Limits(),
            timeouts=Timeouts(),
            follow_redirects=False,
            max_redirects=DEFAULT_MAX_REDIRECTS,
            runtime_workers=1,
            trust_env=False,
            tls=None,
        )


def test_sync_raw_timeout_maps_to_public_timeout(faker: Faker) -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        send_raw_request(
            raw_client=TimeoutRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


async def test_async_raw_timeout_maps_to_public_timeout(faker: Faker) -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        await send_raw_request_async(
            raw_client=TimeoutRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


def test_sync_raw_pool_timeout_maps_to_public_pool_timeout(faker: Faker) -> None:
    with pytest.raises(PoolTimeout, match="request acquire timeout expired"):
        send_raw_request(
            raw_client=PoolTimeoutRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


async def test_async_raw_pool_timeout_maps_to_public_pool_timeout(faker: Faker) -> None:
    with pytest.raises(PoolTimeout, match="request acquire timeout expired"):
        await send_raw_request_async(
            raw_client=PoolTimeoutRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


def test_sync_raw_body_limit_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyTooLargeError, match="max_response_body_size"):
        send_raw_request(
            raw_client=BodyTooLargeRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


async def test_async_raw_body_limit_error_maps_to_public_response_error(faker: Faker) -> None:
    with pytest.raises(ResponseBodyTooLargeError, match="max_response_body_size"):
        await send_raw_request_async(
            raw_client=BodyTooLargeRawClient(),
            method="GET",
            url=faker.url(),
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )
