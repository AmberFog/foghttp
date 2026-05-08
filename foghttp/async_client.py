import asyncio
import builtins
from collections.abc import Mapping
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any
import warnings

from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.options import validate_client_options
from ._client.raw import create_raw_client, send_raw_request_async
from ._client.request import prepare_request
from ._client.response import response_from_raw
from ._client.stats import stats_from_raw
from .errors import ClientClosedError, TimeoutError, UnclosedClientError
from .limits import Limits
from .messages import (
    CLIENT_CLOSED,
    POOL_ACQUIRE_QUEUE_FULL,
    POOL_ACQUIRE_TIMEOUT,
    UNCLOSED_CLIENT,
)
from .pool_stats import PoolStats
from .response import Response
from .timeouts import Timeouts
from .types import HttpVersions


__all__ = ("AsyncClient",)


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
        observability: bool = True,
    ) -> None:
        self._limits = limits or Limits()
        self._timeouts = timeouts or Timeouts()
        validate_client_options(
            cookies=cookies,
            max_redirects=max_redirects,
            trust_env=trust_env,
            http_versions=http_versions,
        )

        self._closed = False
        self._semaphore = asyncio.Semaphore(self._limits.max_connections)
        self._pending_acquires = 0
        self._pool_timeouts = 0
        self._client: _foghttp.RawClient | None = create_raw_client(
            limits=self._limits,
            timeouts=self._timeouts,
            follow_redirects=follow_redirects,
            max_redirects=max_redirects,
            trust_env=trust_env,
        )
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
        if not self._closed:
            self._closed = True
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        content: bytes | str | None = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        self._ensure_open()
        timeouts = timeout or self._timeouts
        request_url, request_headers, body = prepare_request(
            url=url,
            headers=headers,
            params=params,
            content=content,
            json=json,
        )

        started = time.perf_counter()
        acquired = False
        try:
            if self._pending_acquires >= self._limits.max_pending_acquires:
                self._pool_timeouts += 1
                raise TimeoutError(POOL_ACQUIRE_QUEUE_FULL)
            self._pending_acquires += 1
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=timeouts.pool)
                acquired = True
            except builtins.TimeoutError as exc:
                self._pool_timeouts += 1
                raise TimeoutError(POOL_ACQUIRE_TIMEOUT) from exc
            finally:
                self._pending_acquires -= 1

            raw_client = self._client
            if raw_client is None:
                raise ClientClosedError(CLIENT_CLOSED)
            raw = await send_raw_request_async(
                raw_client=raw_client,
                method=method,
                url=request_url,
                headers=request_headers,
                body=body,
                timeouts=timeouts,
            )
        finally:
            if acquired:
                self._semaphore.release()

        return response_from_raw(raw=raw, started=started)

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> Response:
        return await self.request("HEAD", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Response:
        return await self.request("DELETE", url, **kwargs)

    def stats(self) -> PoolStats:
        self._ensure_open()
        return stats_from_raw(
            raw=self._raw_client().stats(),
            pending_acquires=self._pending_acquires,
            pool_timeouts=self._pool_timeouts,
        )

    def dump_pool_state(self) -> dict[str, int]:
        stats = self.stats()
        return {
            "active_connections": stats.active_connections,
            "idle_connections": stats.idle_connections,
            "pending_acquires": stats.pending_acquires,
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError(CLIENT_CLOSED)

    def _raw_client(self) -> Any:
        self._ensure_open()
        raw_client = self._client
        if raw_client is None:
            raise ClientClosedError(CLIENT_CLOSED)
        return raw_client
