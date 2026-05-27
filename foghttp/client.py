__all__ = ("Client",)

import threading
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._client.config import ClientConfig
from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.core import ClientCore
from ._client.options import ClientOptions
from ._client.raw.lifecycle import close_raw_client
from ._client.request_builder.header_policy import validate_safe_request_headers
from ._client.stream_context import StreamContext
from ._client.transport import RawSyncTransport, SyncTransport
from .headers import HeaderSource
from .limits import Limits
from .methods import DELETE, GET, HEAD, PATCH, POST, PUT
from .request import Request
from .response import Response
from .stream_response import StreamResponse
from .timeouts import Timeouts
from .tls import TLSConfig
from .types import HttpVersions, QueryParams, RequestData
from .url import URL


if TYPE_CHECKING:
    from foghttp import _foghttp


class Client(ClientCore):
    _transport: SyncTransport

    def __init__(
        self,
        *,
        base_url: str | URL | None = None,
        headers: HeaderSource = None,
        params: QueryParams = None,
        limits: Limits | None = None,
        timeouts: Timeouts | None = None,
        http_versions: HttpVersions = None,
        follow_redirects: bool = False,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        cookies: bool = False,
        trust_env: bool = False,
        tls: TLSConfig | None = None,
        runtime_workers: int | None = None,
    ) -> None:
        super().__init__(
            config=ClientConfig.from_options(
                ClientOptions(
                    base_url=base_url,
                    headers=headers,
                    params=params,
                    limits=limits,
                    timeouts=timeouts,
                    http_versions=http_versions,
                    follow_redirects=follow_redirects,
                    max_redirects=max_redirects,
                    cookies=cookies,
                    trust_env=trust_env,
                    tls=tls,
                    runtime_workers=runtime_workers,
                ),
            ),
        )
        self._lifecycle_condition = threading.Condition(self._client_lock)
        self._active_sync_send_tokens: set[object] = set()
        self._close_complete = False
        self._transport = self._create_transport()

    def __enter__(self) -> "Client":
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        raw_client = None
        with self._lifecycle_condition:
            if self._closed:
                while not self._close_complete:
                    self._lifecycle_condition.wait()
                return

            self._closed = True
            while self._active_sync_send_tokens:
                self._lifecycle_condition.wait()
            raw_client = self._client
            self._client = None
            if raw_client is None:
                self._close_complete = True
                self._lifecycle_condition.notify_all()
                return

        if raw_client is not None:
            try:
                close_raw_client(raw_client)
            finally:
                with self._lifecycle_condition:
                    self._close_complete = True
                    self._lifecycle_condition.notify_all()

    def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        self._ensure_open()
        request = self.build_request(
            method,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
        )
        return self.send(request, timeout=timeout)

    def send(self, request: Request, *, timeout: Timeouts | None = None) -> Response:
        sync_send_token = object()
        try:
            self._begin_sync_send(sync_send_token)
            validate_safe_request_headers(request.headers)
            timeouts = self._request_timeouts(timeout)
            return self._transport.send(request, timeouts=timeouts)
        finally:
            self._finish_sync_send(sync_send_token)

    def stream(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> StreamContext:
        self._ensure_open()
        request = self.build_request(
            method,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
        )
        return StreamContext(lambda: self._send_stream(request, timeout=timeout))

    def _send_stream(self, request: Request, *, timeout: Timeouts | None = None) -> StreamResponse:
        sync_send_token = object()
        try:
            self._begin_sync_send(sync_send_token)
            validate_safe_request_headers(request.headers)
            timeouts = self._request_timeouts(timeout)
            return self._transport.stream(request, timeouts=timeouts)
        finally:
            self._finish_sync_send(sync_send_token)

    def get(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            GET,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def head(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            HEAD,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def post(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            POST,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def put(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            PUT,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def patch(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            PATCH,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def delete(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return self.request(
            DELETE,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def _begin_sync_send(self, token: object) -> None:
        with self._lifecycle_condition:
            self._ensure_open()
            self._active_sync_send_tokens.add(token)

    def _sync_send_raw_client(self) -> "_foghttp.RawClient":
        with self._lifecycle_condition:
            return self._raw_client_locked()

    def _create_transport(self) -> SyncTransport:
        return RawSyncTransport(self._sync_send_raw_client)

    def _finish_sync_send(self, token: object) -> None:
        with self._lifecycle_condition:
            self._finish_sync_send_locked(token)

    def _finish_sync_send_locked(self, token: object) -> None:
        self._active_sync_send_tokens.discard(token)
        if not self._active_sync_send_tokens:
            self._lifecycle_condition.notify_all()
