__all__ = ("AsyncClient",)

from types import TracebackType
from typing import Any

from ._client.config import ClientConfig
from ._client.constants import DEFAULT_MAX_REDIRECTS
from ._client.core import ClientCore
from ._client.lifecycle_debug import (
    LifecycleDebugRequestToken,
    async_lifecycle_debug_leak_message,
)
from ._client.options import ClientOptions
from ._client.raw.lifecycle import close_raw_client
from ._client.request_builder.header_policy import validate_safe_request_headers
from ._client.stats import stats_from_raw
from ._client.stream_context import AsyncStreamContext
from ._client.telemetry import (
    TelemetryRequestContext,
    emit_buffered_response_telemetry,
    emit_request_error_telemetry,
    emit_stream_response_headers_telemetry,
    start_request_telemetry,
)
from ._client.transport import AsyncTransport, RawAsyncTransport
from .errors import LifecycleError
from .headers import HeaderSource
from .lifecycle_debug import (
    AsyncLifecycleDebugConfig,
    AsyncLifecycleDebugRequestMode,
    AsyncLifecycleDebugSnapshot,
)
from .limits import Limits
from .methods import DELETE, GET, HEAD, PATCH, POST, PUT
from .request import Request
from .response import Response
from .stream_response import AsyncStreamResponse
from .stream_response.bindings import bind_stream_lifecycle_debug, bind_stream_telemetry
from .telemetry import TelemetryConfig, TelemetryRequestMode
from .timeouts import Timeouts
from .tls import TLSConfig
from .types import HttpVersions, QueryParams, RequestData
from .url import URL


class AsyncClient(ClientCore):
    _transport: AsyncTransport

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
        telemetry: TelemetryConfig | None = None,
        lifecycle_debug: AsyncLifecycleDebugConfig | None = None,
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
                    telemetry=telemetry,
                    lifecycle_debug=lifecycle_debug,
                ),
            ),
        )
        self._transport = self._create_transport()

    async def __aenter__(self) -> "AsyncClient":
        self._ensure_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._close(raise_strict_lifecycle_errors=exc_type is None)

    async def aclose(self) -> None:
        self._close(raise_strict_lifecycle_errors=True)

    def dump_lifecycle_debug(self) -> AsyncLifecycleDebugSnapshot:
        with self._client_lock:
            return self._lifecycle_debug_snapshot_locked()

    def assert_no_lifecycle_leaks(self) -> None:
        snapshot = self.dump_lifecycle_debug()
        if snapshot.has_leaks:
            raise LifecycleError(async_lifecycle_debug_leak_message(snapshot))

    async def request(
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
        return await self.send(request, timeout=timeout)

    async def send(self, request: Request, *, timeout: Timeouts | None = None) -> Response:
        telemetry_context = self._telemetry.request_context(request, mode=TelemetryRequestMode.BUFFERED)
        telemetry_started = False
        lifecycle_debug_token: LifecycleDebugRequestToken = None
        try:
            lifecycle_debug_token = self._begin_async_request_lifecycle_debug(request, mode="buffered")
            telemetry_started = start_request_telemetry(telemetry_context)
            validate_safe_request_headers(request.headers)
            response = await self._transport.send(request, timeouts=self._request_timeouts(timeout))
        except BaseException as error:
            emit_request_error_telemetry(
                telemetry_context,
                telemetry_started=telemetry_started,
                error=error,
            )
            raise
        else:
            emit_buffered_response_telemetry(telemetry_context, response)
            return response
        finally:
            self._lifecycle_debug.finish_request(lifecycle_debug_token)

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
    ) -> AsyncStreamContext:
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
        return AsyncStreamContext(self._send_stream(request, timeout=timeout))

    async def get(
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
        return await self.request(
            GET,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
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
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            HEAD,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
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
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            POST,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
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
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            PUT,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
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
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            PATCH,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
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
        data: RequestData = None,
        json: Any = None,
        timeout: Timeouts | None = None,
    ) -> Response:
        return await self.request(
            DELETE,
            url,
            headers=headers,
            params=params,
            content=content,
            data=data,
            json=json,
            timeout=timeout,
        )

    def _create_transport(self) -> AsyncTransport:
        return RawAsyncTransport(self._raw_client)

    def _close(self, *, raise_strict_lifecycle_errors: bool) -> None:
        strict_snapshot = None
        raw_client = None
        with self._client_lock:
            if not self._closed:
                strict_snapshot = self._strict_lifecycle_debug_snapshot_locked()
                self._closed = True
                raw_client = self._client
                self._client = None
        if raw_client is not None:
            close_raw_client(raw_client)
        if raise_strict_lifecycle_errors and strict_snapshot is not None and strict_snapshot.has_leaks:
            raise LifecycleError(async_lifecycle_debug_leak_message(strict_snapshot))

    def _begin_async_request_lifecycle_debug(
        self,
        request: Request,
        *,
        mode: AsyncLifecycleDebugRequestMode,
    ) -> LifecycleDebugRequestToken:
        self._ensure_open()
        return self._lifecycle_debug.start_request(request, mode=mode)

    async def _send_stream(
        self,
        request: Request,
        *,
        timeout: Timeouts | None = None,
    ) -> AsyncStreamResponse:
        telemetry_context = self._telemetry.request_context(request, mode=TelemetryRequestMode.STREAM)
        telemetry_started = False
        lifecycle_debug_bound = False
        lifecycle_debug_token: LifecycleDebugRequestToken = None
        try:
            lifecycle_debug_token = self._begin_async_request_lifecycle_debug(request, mode="stream")
            telemetry_started = start_request_telemetry(telemetry_context)
            validate_safe_request_headers(request.headers)
            response = await self._transport.stream(request, timeouts=self._request_timeouts(timeout))
        except BaseException as error:
            emit_request_error_telemetry(
                telemetry_context,
                telemetry_started=telemetry_started,
                error=error,
            )
            raise
        else:
            if lifecycle_debug_token is not None:
                bind_stream_lifecycle_debug(
                    response,
                    lambda: self._lifecycle_debug.finish_request(lifecycle_debug_token),
                )
                lifecycle_debug_bound = True
            _bind_stream_response_telemetry(telemetry_context, response)
            return response
        finally:
            if not lifecycle_debug_bound:
                self._lifecycle_debug.finish_request(lifecycle_debug_token)

    def _strict_lifecycle_debug_snapshot_locked(self) -> AsyncLifecycleDebugSnapshot | None:
        if not self._lifecycle_debug.strict:
            return None
        return self._lifecycle_debug_snapshot_locked()

    def _lifecycle_debug_snapshot_locked(self) -> AsyncLifecycleDebugSnapshot:
        raw_client = self._client
        stats = None if raw_client is None else stats_from_raw(raw=raw_client.stats())
        return self._lifecycle_debug.snapshot(
            closed=self._closed,
            stats=stats,
        )

    def _unclosed_client_message(self) -> str:
        return self._lifecycle_debug.unclosed_warning_message(super()._unclosed_client_message())


def _bind_stream_response_telemetry(
    telemetry_context: TelemetryRequestContext | None,
    response: AsyncStreamResponse,
) -> None:
    if telemetry_context is None:
        return

    try:
        emit_stream_response_headers_telemetry(telemetry_context, response)
    except BaseException:
        response.close()
        raise
    bind_stream_telemetry(response, telemetry_context)
