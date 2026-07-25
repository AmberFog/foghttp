__all__ = (
    "AsyncTransport",
    "RawAsyncTransport",
    "RawSyncTransport",
    "SyncTransport",
)

import time
import typing

from .. import stream_response as stream_response_models
from ..request import Request
from ..response import Response
from ..timeouts import Timeouts
from .proxy import ProxyResolver
from .raw import requests as raw_requests
from .response import async_stream_response_from_raw, response_from_raw, stream_response_from_raw
from .telemetry import current_native_request_id
from .transport_requests import raw_request_options


if typing.TYPE_CHECKING:
    from foghttp import _foghttp


RawClientProvider = typing.Callable[[], "_foghttp.RawClient"]


class SyncTransport(typing.Protocol):
    def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...
    def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
    ) -> stream_response_models.StreamResponse: ...


class AsyncTransport(typing.Protocol):
    async def send(self, request: Request, *, timeouts: Timeouts) -> Response: ...
    async def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
    ) -> stream_response_models.AsyncStreamResponse: ...


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
            telemetry_request_id=current_native_request_id(),
        )
        return response_from_raw(raw=raw, started=started, extensions=request.extensions)

    def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
    ) -> stream_response_models.StreamResponse:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = raw_requests.send_raw_stream_request(
            raw_client=self._raw_client_provider(),
            request=raw_request,
            telemetry_request_id=current_native_request_id(),
        )
        return stream_response_from_raw(raw=raw, started=started, extensions=request.extensions)


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
            telemetry_request_id=current_native_request_id(),
        )
        return response_from_raw(raw=raw, started=started, extensions=request.extensions)

    async def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
    ) -> stream_response_models.AsyncStreamResponse:
        started = time.perf_counter()
        raw_request = raw_request_options(request, timeouts, self._proxy_resolver)
        raw = await raw_requests.send_raw_stream_request_async(
            raw_client=self._raw_client_provider(),
            request=raw_request,
            telemetry_request_id=current_native_request_id(),
        )
        return async_stream_response_from_raw(raw=raw, started=started, extensions=request.extensions)
