import pytest

from foghttp import _foghttp
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.raw import create_raw_client, send_raw_request, send_raw_request_async
from foghttp.errors import TimeoutError
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


class TimeoutRawClient:
    def request(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)


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
        )


def test_sync_raw_timeout_maps_to_public_timeout() -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        send_raw_request(
            raw_client=TimeoutRawClient(),
            method="GET",
            url="http://example.com",
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )


async def test_async_raw_timeout_maps_to_public_timeout() -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        await send_raw_request_async(
            raw_client=TimeoutRawClient(),
            method="GET",
            url="http://example.com",
            headers=[],
            body=None,
            timeouts=Timeouts(),
        )
