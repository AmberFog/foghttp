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
from ..stream_response import AsyncStreamResponse, StreamResponse
from ..timeouts import Timeouts
from .proxy import ProxyResolver
from .raw import requests as raw_requests
from .response import async_stream_response_from_raw, response_from_raw, stream_response_from_raw
from .transport_requests import raw_request_options


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
    def __init__(self, raw_client_provider: RawClientProvider, *, proxy_resolver: ProxyResolver) -> None:
        self._raw_client_provider = raw_client_provider
        self._proxy_resolver = proxy_resolver

    def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = raw_requests.send_raw_request(
            raw_client=self._raw_client_provider(),
            request=raw_request,
        )
        return response_from_raw(raw=raw, started=started)

    def stream(self, request: Request, *, timeouts: Timeouts) -> StreamResponse:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = raw_requests.send_raw_stream_request(
            raw_client=self._raw_client_provider(),
            request=raw_request,
        )
        return stream_response_from_raw(raw=raw, started=started)


class RawAsyncTransport:
    def __init__(self, raw_client_provider: RawClientProvider, *, proxy_resolver: ProxyResolver) -> None:
        self._raw_client_provider = raw_client_provider
        self._proxy_resolver = proxy_resolver

    async def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = await raw_requests.send_raw_request_async(
            raw_client=self._raw_client_provider(),
            request=raw_request,
        )
        return response_from_raw(raw=raw, started=started)

    async def stream(self, request: Request, *, timeouts: Timeouts) -> AsyncStreamResponse:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = await raw_requests.send_raw_stream_request_async(
            raw_client=self._raw_client_provider(),
            request=raw_request,
        )
        return async_stream_response_from_raw(raw=raw, started=started)
