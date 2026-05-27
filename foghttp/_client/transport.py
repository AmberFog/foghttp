__all__ = (
    "AsyncTransport",
    "RawAsyncTransport",
    "RawSyncTransport",
    "SyncTransport",
)

from collections.abc import Callable
import time
from typing import TYPE_CHECKING, Protocol, TypeAlias

from .._request_body import RequestBody, request_body
from ..request import Request
from ..response import Response
from ..stream_response import AsyncStreamResponse, StreamResponse
from ..timeouts import Timeouts
from .raw.requests import (
    RawRequestOptions,
    send_raw_request,
    send_raw_request_async,
    send_raw_stream_request,
    send_raw_stream_request_async,
)
from .response import async_stream_response_from_raw, response_from_raw, stream_response_from_raw


if TYPE_CHECKING:
    from foghttp import _foghttp


RawClientProvider: TypeAlias = Callable[[], "_foghttp.RawClient"]


class SyncTransport(Protocol):
    def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...
    def stream(self, request: Request, *, timeouts: Timeouts) -> StreamResponse: ...


class AsyncTransport(Protocol):
    async def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...
    async def stream(self, request: Request, *, timeouts: Timeouts) -> AsyncStreamResponse: ...


class RawSyncTransport:
    def __init__(self, raw_client_provider: RawClientProvider) -> None:
        self._raw_client_provider = raw_client_provider

    def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        body = request_body(request)
        raw = send_raw_request(
            raw_client=self._raw_client_provider(),
            request=_raw_request_options(request, body, timeouts),
        )
        return response_from_raw(raw=raw, started=started)

    def stream(self, request: Request, *, timeouts: Timeouts) -> StreamResponse:
        started = time.perf_counter()
        body = request_body(request)
        raw = send_raw_stream_request(
            raw_client=self._raw_client_provider(),
            request=_raw_request_options(request, body, timeouts),
        )
        return stream_response_from_raw(raw=raw, started=started)


class RawAsyncTransport:
    def __init__(self, raw_client_provider: RawClientProvider) -> None:
        self._raw_client_provider = raw_client_provider

    async def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        body = request_body(request)
        raw = await send_raw_request_async(
            raw_client=self._raw_client_provider(),
            request=_raw_request_options(request, body, timeouts),
        )
        return response_from_raw(raw=raw, started=started)

    async def stream(self, request: Request, *, timeouts: Timeouts) -> AsyncStreamResponse:
        started = time.perf_counter()
        body = request_body(request)
        raw = await send_raw_stream_request_async(
            raw_client=self._raw_client_provider(),
            request=_raw_request_options(request, body, timeouts),
        )
        return async_stream_response_from_raw(raw=raw, started=started)


def _raw_request_options(
    request: Request,
    body: RequestBody,
    timeouts: Timeouts,
) -> RawRequestOptions:
    return RawRequestOptions(
        method=request.method,
        url=request.url,
        headers=request.headers.multi_items(),
        body=body.content,
        body_replayable=body.replayable,
        timeouts=timeouts,
    )
