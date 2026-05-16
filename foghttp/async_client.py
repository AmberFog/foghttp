__all__ = ("AsyncClient",)

import threading
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any
import warnings

from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.options import validate_client_options
from ._client.raw import close_raw_client, create_raw_client, send_raw_request_async
from ._client.request import prepare_request
from ._client.response import response_from_raw
from ._client.stats import stats_from_raw
from .errors import ClientClosedError, UnclosedClientError
from .headers import HeaderSource
from .limits import Limits
from .messages import CLIENT_CLOSED, UNCLOSED_CLIENT
from .request import Request
from .response import Response
from .timeouts import Timeouts
from .tls import TLSConfig
from .transport_stats import TransportStats
from .types import HttpVersions, QueryParams
from .url import URL


if TYPE_CHECKING:
    from foghttp import _foghttp


class AsyncClient:
    def __init__(
        self,
        *,
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
        self._limits = limits or Limits()
        self._timeouts = timeouts or Timeouts()
        validate_client_options(
            cookies=cookies,
            max_redirects=max_redirects,
            runtime_workers=runtime_workers,
            trust_env=trust_env,
            http_versions=http_versions,
        )

        self._closed = False
        self._client_lock = threading.Lock()
        self._follow_redirects = follow_redirects
        self._max_redirects = max_redirects
        self._runtime_workers = runtime_workers
        self._trust_env = trust_env
        self._tls = tls
        self._client: _foghttp.RawClient | None = None
        self._observability = observability

    async def __aenter__(self) -> "AsyncClient":
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __del__(self) -> None:
        if getattr(self, "_closed", True) is False:
            warnings.warn(UNCLOSED_CLIENT, UnclosedClientError, stacklevel=2)

    async def aclose(self) -> None:
        raw_client = None
        with self._client_lock:
            if not self._closed:
                self._closed = True
                raw_client = self._client
                self._client = None
        if raw_client is not None:
            close_raw_client(raw_client)

    async def request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
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
            json=json,
        )
        return await self.send(request, timeout=timeout)

    def build_request(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
    ) -> Request:
        return prepare_request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            content=content,
            json=json,
        )

    async def send(self, request: Request, *, timeout: Timeouts | None = None) -> Response:
        self._ensure_open()
        timeouts = timeout or self._timeouts
        started = time.perf_counter()
        raw_client = self._raw_client()
        raw = await send_raw_request_async(
            raw_client=raw_client,
            method=request.method,
            url=request.url,
            headers=request.headers.multi_items(),
            body=request.content,
            timeouts=timeouts,
        )

        return response_from_raw(raw=raw, started=started)

    async def get(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "GET",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    async def head(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "HEAD",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    async def post(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "POST",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    async def put(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "PUT",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    async def patch(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "PATCH",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    async def delete(
        self,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        params: QueryParams = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            "DELETE",
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )

    def stats(self) -> TransportStats:
        self._ensure_open()
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            raw_stats = None if raw_client is None else raw_client.stats()
        if raw_stats is None:
            return TransportStats()
        return stats_from_raw(raw=raw_stats)

    def dump_transport_state(self) -> dict[str, int]:
        stats = self.stats()
        return {
            "active_requests": stats.active_requests,
            "pending_requests": stats.pending_requests,
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError(CLIENT_CLOSED)

    def _raw_client(self) -> "_foghttp.RawClient":
        self._ensure_open()
        raw_client = self._client
        if raw_client is not None:
            return raw_client
        with self._client_lock:
            self._ensure_open()
            raw_client = self._client
            if raw_client is None:
                raw_client = create_raw_client(
                    limits=self._limits,
                    timeouts=self._timeouts,
                    follow_redirects=self._follow_redirects,
                    max_redirects=self._max_redirects,
                    runtime_workers=self._runtime_workers,
                    trust_env=self._trust_env,
                    tls=self._tls,
                )
                self._client = raw_client
            return raw_client
