__all__ = (
    "AsyncFailingTransport",
    "AsyncRecordingTransport",
    "AsyncTransportClient",
    "SyncFailingTransport",
    "SyncRecordingTransport",
    "SyncTransportClient",
    "TransportCall",
    "response_for_request",
)

from dataclasses import dataclass, field

import foghttp
from foghttp.headers import Headers
from foghttp.request import Request
from foghttp.request_info import RequestInfo
from foghttp.response import Response
from foghttp.status_codes.success import OK
from foghttp.timeouts import Timeouts


_HTTP_1_1 = "HTTP/1.1"


@dataclass(frozen=True, slots=True)
class TransportCall:
    request: Request
    timeouts: Timeouts
    decode_content: bool | None = None
    auto_accept_encoding: bool = False


@dataclass(slots=True)
class SyncRecordingTransport:
    response: Response
    calls: list[TransportCall] = field(default_factory=list)

    def send(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        auto_accept_encoding: bool = False,
    ) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts, auto_accept_encoding=auto_accept_encoding))
        return self.response


@dataclass(slots=True)
class SyncFailingTransport:
    error: BaseException
    calls: list[TransportCall] = field(default_factory=list)

    def send(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        auto_accept_encoding: bool = False,
    ) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts, auto_accept_encoding=auto_accept_encoding))
        raise self.error

    def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        decode_content: bool = False,
        auto_accept_encoding: bool = False,
    ) -> foghttp.StreamResponse:
        self.calls.append(
            TransportCall(
                request=request,
                timeouts=timeouts,
                decode_content=decode_content,
                auto_accept_encoding=auto_accept_encoding,
            ),
        )
        raise self.error


@dataclass(slots=True)
class AsyncRecordingTransport:
    response: Response
    calls: list[TransportCall] = field(default_factory=list)

    async def send(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        auto_accept_encoding: bool = False,
    ) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts, auto_accept_encoding=auto_accept_encoding))
        return self.response


@dataclass(slots=True)
class AsyncFailingTransport:
    error: BaseException
    calls: list[TransportCall] = field(default_factory=list)

    async def send(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        auto_accept_encoding: bool = False,
    ) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts, auto_accept_encoding=auto_accept_encoding))
        raise self.error

    async def stream(
        self,
        request: Request,
        *,
        timeouts: Timeouts,
        decode_content: bool = False,
        auto_accept_encoding: bool = False,
    ) -> foghttp.AsyncStreamResponse:
        self.calls.append(
            TransportCall(
                request=request,
                timeouts=timeouts,
                decode_content=decode_content,
                auto_accept_encoding=auto_accept_encoding,
            ),
        )
        raise self.error


SyncTestTransport = SyncRecordingTransport | SyncFailingTransport
AsyncTestTransport = AsyncRecordingTransport | AsyncFailingTransport


class SyncTransportClient(foghttp.Client):
    def __init__(
        self,
        transport: SyncTestTransport,
        *,
        timeouts: Timeouts,
        telemetry: foghttp.TelemetryConfig | None = None,
    ) -> None:
        self._test_transport = transport
        super().__init__(timeouts=timeouts, telemetry=telemetry)

    def _create_transport(self) -> SyncTestTransport:
        return self._test_transport


class AsyncTransportClient(foghttp.AsyncClient):
    def __init__(
        self,
        transport: AsyncTestTransport,
        *,
        timeouts: Timeouts,
        telemetry: foghttp.TelemetryConfig | None = None,
    ) -> None:
        self._test_transport = transport
        super().__init__(timeouts=timeouts, telemetry=telemetry)

    def _create_transport(self) -> AsyncTestTransport:
        return self._test_transport


def response_for_request(request: Request) -> Response:
    return Response(
        status_code=OK,
        headers=Headers(),
        content=b"",
        url=request.url,
        request=RequestInfo(
            method=request.method,
            url=request.url,
            headers=request.headers.copy(),
            extensions=request.extensions,
        ),
        http_version=_HTTP_1_1,
        elapsed=0.0,
    )
