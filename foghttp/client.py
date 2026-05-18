__all__ = ("Client",)

import threading
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any

from ._client.config import ClientConfig
from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.core import ClientCore
from ._client.raw import close_raw_client, send_raw_request
from ._client.request_builder.header_policy import validate_safe_request_headers
from ._client.response import response_from_raw
from .headers import HeaderSource
from .limits import Limits
from .methods import DELETE, GET, HEAD, PATCH, POST, PUT
from .request import Request
from .response import Response
from .timeouts import Timeouts
from .tls import TLSConfig
from .types import HttpVersions, QueryParams, RequestData
from .url import URL


if TYPE_CHECKING:
    from foghttp import _foghttp


class Client(ClientCore):
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
        observability: bool = True,
    ) -> None:
        super().__init__(
            config=ClientConfig.from_options(
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
                observability=observability,
            ),
        )
        self._lifecycle_condition = threading.Condition(self._client_lock)
        self._active_sync_sends = 0
        self._close_complete = False

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
            while self._active_sync_sends:
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
        self._ensure_open()
        validate_safe_request_headers(request.headers)
        timeouts = self._request_timeouts(timeout)
        started = time.perf_counter()
        raw_client = self._begin_sync_send()
        try:
            raw = send_raw_request(
                raw_client=raw_client,
                method=request.method,
                url=request.url,
                headers=request.headers.multi_items(),
                body=request.content,
                timeouts=timeouts,
            )

            return response_from_raw(raw=raw, started=started)
        finally:
            self._finish_sync_send()

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

    def _begin_sync_send(self) -> "_foghttp.RawClient":
        with self._lifecycle_condition:
            self._ensure_open()
            self._active_sync_sends += 1
            try:
                return self._raw_client_locked()
            except BaseException:
                self._finish_sync_send_locked()
                raise

    def _finish_sync_send(self) -> None:
        with self._lifecycle_condition:
            self._finish_sync_send_locked()

    def _finish_sync_send_locked(self) -> None:
        self._active_sync_sends -= 1
        if self._active_sync_sends == 0:
            self._lifecycle_condition.notify_all()
