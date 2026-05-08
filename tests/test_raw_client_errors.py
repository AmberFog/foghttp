import pytest

from foghttp import _foghttp
from foghttp._client.raw import send_raw_request, send_raw_request_async
from foghttp.errors import TimeoutError
from foghttp.timeouts import Timeouts


class TimeoutRawClient:
    def request(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)

    async def request_async(self, *_args: object) -> object:
        msg = "request timed out"
        raise _foghttp.FogHttpTimeoutError(msg)


def test_sync_raw_timeout_maps_to_public_timeout() -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        send_raw_request(
            raw_client=TimeoutRawClient(),
            method="GET",
            url="http://example.com",
            headers={},
            body=None,
            timeouts=Timeouts(),
        )


async def test_async_raw_timeout_maps_to_public_timeout() -> None:
    with pytest.raises(TimeoutError, match="request timed out"):
        await send_raw_request_async(
            raw_client=TimeoutRawClient(),
            method="GET",
            url="http://example.com",
            headers={},
            body=None,
            timeouts=Timeouts(),
        )
