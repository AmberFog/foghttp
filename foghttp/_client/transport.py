__all__ = (
    "AsyncTransport",
    "RawAsyncTransport",
    "RawSyncTransport",
    "SyncTransport",
)

from collections.abc import Callable
import time
from typing import TYPE_CHECKING, Protocol, TypeAlias

from .._request_body import request_body
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
    def __init__(self, raw_client_provider: RawClientProvider) -> None:
        self._raw_client_provider = raw_client_provider

    def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        body = request_body(request)
        raw = send_raw_request(
            raw_client=self._raw_client_provider(),
            method=request.method,
            url=request.url,
            headers=request.headers.multi_items(),
            body=body.content,
            body_replayable=body.replayable,
            timeouts=timeouts,
        )
        return response_from_raw(raw=raw, started=started)


class RawAsyncTransport:
    def __init__(self, raw_client_provider: RawClientProvider) -> None:
        self._raw_client_provider = raw_client_provider

    async def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        body = request_body(request)
        raw = await send_raw_request_async(
            raw_client=self._raw_client_provider(),
            method=request.method,
            url=request.url,
            headers=request.headers.multi_items(),
            body=body.content,
            body_replayable=body.replayable,
            timeouts=timeouts,
        )
        return response_from_raw(raw=raw, started=started)
