__all__ = ("AsyncClient",)

import time
from types import TracebackType
from typing import Any

from ._client.config import ClientConfig
from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.core import ClientCore
from ._client.raw import close_raw_client, send_raw_request_async
from ._client.response import response_from_raw
from .headers import HeaderSource
from .limits import Limits
from .methods import DELETE, GET, HEAD, PATCH, POST, PUT
from .request import Request
from .response import Response
from .timeouts import Timeouts
from .tls import TLSConfig
from .types import HttpVersions, QueryParams
from .url import URL


class AsyncClient(ClientCore):
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
        super().__init__(
            config=ClientConfig.from_options(
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

    async def send(self, request: Request, *, timeout: Timeouts | None = None) -> Response:
        self._ensure_open()
        timeouts = self._request_timeouts(timeout)
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
            GET,
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
            HEAD,
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
            POST,
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
            PUT,
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
            PATCH,
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
            DELETE,
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
            timeout=timeout,
        )
