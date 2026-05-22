__all__ = (
    "AsyncRecordingTransport",
    "AsyncTransportClient",
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


@dataclass(slots=True)
class SyncRecordingTransport:
    response: Response
    calls: list[TransportCall] = field(default_factory=list)

    def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts))
        return self.response


@dataclass(slots=True)
class AsyncRecordingTransport:
    response: Response
    calls: list[TransportCall] = field(default_factory=list)

    async def send(self, request: Request, *, timeouts: Timeouts) -> Response:
        self.calls.append(TransportCall(request=request, timeouts=timeouts))
        return self.response


class SyncTransportClient(foghttp.Client):
    def __init__(self, transport: SyncRecordingTransport, *, timeouts: Timeouts) -> None:
        self._test_transport = transport
        super().__init__(timeouts=timeouts)

    def _create_transport(self) -> SyncRecordingTransport:
        return self._test_transport


class AsyncTransportClient(foghttp.AsyncClient):
    def __init__(self, transport: AsyncRecordingTransport, *, timeouts: Timeouts) -> None:
        self._test_transport = transport
        super().__init__(timeouts=timeouts)

    def _create_transport(self) -> AsyncRecordingTransport:
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
        ),
        http_version=_HTTP_1_1,
        elapsed=0.0,
    )
