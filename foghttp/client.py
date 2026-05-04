import asyncio
import time
import warnings
from types import TracebackType
from typing import Any, Mapping

from . import _foghttp
from .body import encode_body
from .client_closed_error import ClientClosedError
from .limits import Limits
from .messages import (
    CLIENT_CLOSED,
    COOKIES_UNSUPPORTED,
    HTTP_VERSION_UNSUPPORTED,
    POOL_ACQUIRE_QUEUE_FULL,
    POOL_ACQUIRE_TIMEOUT,
    REDIRECTS_UNSUPPORTED,
    TRUST_ENV_UNSUPPORTED,
    UNCLOSED_CLIENT,
)
from .pool_stats import PoolStats
from .request_error import RequestError
from .response import Response
from .timeout_error import TimeoutError
from .timeouts import Timeouts
from .unclosed_client_error import UnclosedClientError
from .url import merge_params


class AsyncClient:
    def __init__(
        self,
        *,
        limits: Limits | None = None,
        timeouts: Timeouts | None = None,
        http_versions: list[str] | None = None,
        follow_redirects: bool = False,
        cookies: bool = False,
        trust_env: bool = False,
        observability: bool = True,
    ) -> None:
        self._limits = limits or Limits()
        self._timeouts = timeouts or Timeouts()
        if cookies:
            raise NotImplementedError(COOKIES_UNSUPPORTED)
        if follow_redirects:
            raise NotImplementedError(REDIRECTS_UNSUPPORTED)
        if trust_env:
            raise NotImplementedError(TRUST_ENV_UNSUPPORTED)
        if http_versions and http_versions != ["HTTP/1.1"]:
            raise NotImplementedError(HTTP_VERSION_UNSUPPORTED)

        self._closed = False
        self._semaphore = asyncio.Semaphore(self._limits.max_connections)
        self._pending_acquires = 0
        self._pool_timeouts = 0
        self._client = _foghttp.RawClient(
            self._limits.max_connections,
            self._limits.max_connections_per_host,
            self._limits.idle_timeout,
            self._limits.keepalive,
            self._timeouts.connect,
            follow_redirects,
            trust_env,
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
        self._closed = True

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
        request_url = merge_params(url, params)
        request_headers = dict(headers or {})
        body = encode_body(content=content, json=json, headers=request_headers)

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
            except asyncio.TimeoutError as exc:
                self._pool_timeouts += 1
                raise TimeoutError(POOL_ACQUIRE_TIMEOUT) from exc
            finally:
                self._pending_acquires -= 1

            raw = await asyncio.to_thread(
                self._client.request,
                method.upper(),
                request_url,
                request_headers,
                body,
                timeouts.connect,
                timeouts.total,
            )
        except _foghttp.FogHttpTimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        except _foghttp.FogHttpError as exc:
            raise RequestError(str(exc)) from exc
        finally:
            if acquired:
                self._semaphore.release()

        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        return Response(
            status_code=raw.status_code,
            headers=raw.headers,
            content=raw.content,
            url=raw.url,
            http_version=raw.http_version,
            elapsed=elapsed,
        )

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await self.request("GET", url, **kwargs)

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
        raw = self._client.stats()
        return PoolStats(
            active_connections=raw.active_connections,
            idle_connections=raw.idle_connections,
            pending_acquires=self._pending_acquires,
            total_requests=raw.total_requests,
            failed_requests=raw.failed_requests,
            reused_connections=raw.reused_connections,
            opened_connections=raw.opened_connections,
            closed_connections=raw.closed_connections,
            pool_timeouts=raw.pool_timeouts + self._pool_timeouts,
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
