__all__ = (
    "AsyncTransport",
    "RawAsyncTransport",
    "RawSyncTransport",
    "SyncTransport",
)

from collections.abc import Callable
import time
from typing import TYPE_CHECKING, Protocol, TypeAlias

from ..request import Request
from ..response import Response
from ..timeouts import Timeouts
from .raw import send_raw_request, send_raw_request_async
from .response import response_from_raw


if TYPE_CHECKING:
    from foghttp import _foghttp


RawClientProvider: TypeAlias = Callable[[], "_foghttp.RawClient"]


class SyncTransport(Protocol):
    def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...


class AsyncTransport(Protocol):
    async def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...


class RawSyncTransport:
    def __init__(self, raw_client: RawClientProvider) -> None:
        self._raw_client = raw_client

    def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        raw = send_raw_request(
            raw_client=self._raw_client(),
            method=request.method,
            url=request.url,
            headers=request.headers.multi_items(),
            body=request.content,
            timeouts=timeouts,
        )
        return response_from_raw(raw=raw, started=started)


class RawAsyncTransport:
    def __init__(self, raw_client: RawClientProvider) -> None:
        self._raw_client = raw_client

    async def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        raw = await send_raw_request_async(
            raw_client=self._raw_client(),
            method=request.method,
            url=request.url,
            headers=request.headers.multi_items(),
            body=request.content,
            timeouts=timeouts,
        )
        return response_from_raw(raw=raw, started=started)
