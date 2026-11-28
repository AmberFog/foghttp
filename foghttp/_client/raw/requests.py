__all__ = (
    "RawRequestOptions",
    "send_raw_request",
    "send_raw_request_async",
    "send_raw_stream_request",
    "send_raw_stream_request_async",
)

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import sys

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..._request_body import RequestBody
from ..._upload_body import prepare_async_upload_body, prepare_sync_upload_body
from ..._upload_body.models import AsyncFactoryProtocolError, AsyncUploadBody, SyncUploadBody
from ...request_extensions import RequestExtensions
from ...timeouts import Timeouts
from ..proxy import ProxyTransportPolicy
from .errors import raise_public_raw_error


@dataclass(frozen=True, slots=True)
class RawRequestOptions:
    method: str
    url: str
    headers: Sequence[tuple[str, str]]
    body: RequestBody
    use_proxy_transport: bool
    proxy_policy: ProxyTransportPolicy
    timeouts: Timeouts
    extensions: RequestExtensions | None = None
    auth_override_headers: Sequence[str] | None = None
    auth_removed_headers: Sequence[str] = ()


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
    telemetry_request_id: int | None = None,
) -> _foghttp.RawResponse:
    body = prepare_sync_upload_body(request.body, raw_client=raw_client)
    try:
        return raw_client.request(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
            auth_override_headers=request.auth_override_headers,
            auth_removed_headers=request.auth_removed_headers,
            extensions=request.extensions,
            body=body.buffered_body,
            body_stream=body.raw_body,
            body_replayable=request.body.replayable,
            use_proxy_transport=request.use_proxy_transport,
            proxy_policy=request.proxy_policy.value,
            pool_timeout=request.timeouts.pool,
            read_timeout=request.timeouts.read,
            write_timeout=request.timeouts.write,
            total_timeout=request.timeouts.total,
            telemetry_request_id=telemetry_request_id,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        _close_body(body)


def send_raw_stream_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
    telemetry_request_id: int | None = None,
    decode_content: bool = False,
) -> _foghttp.RawStreamResponse:
    body = prepare_sync_upload_body(request.body, raw_client=raw_client)
    try:
        return raw_client.request_stream(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
            auth_override_headers=request.auth_override_headers,
            auth_removed_headers=request.auth_removed_headers,
            extensions=request.extensions,
            body=body.buffered_body,
            body_stream=body.raw_body,
            body_replayable=request.body.replayable,
            use_proxy_transport=request.use_proxy_transport,
            proxy_policy=request.proxy_policy.value,
            pool_timeout=request.timeouts.pool,
            read_timeout=request.timeouts.read,
            write_timeout=request.timeouts.write,
            total_timeout=request.timeouts.total,
            telemetry_request_id=telemetry_request_id,
            decode_content=decode_content,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        _close_body(body)


async def send_raw_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
    telemetry_request_id: int | None = None,
) -> _foghttp.RawResponse:
    body = prepare_async_upload_body(request.body, raw_client=raw_client)
    factory_failed = False
    try:
        return await raw_client.request_async(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
            auth_override_headers=request.auth_override_headers,
            auth_removed_headers=request.auth_removed_headers,
            extensions=request.extensions,
            body=body.buffered_body,
            body_stream=body.raw_body,
            body_replayable=request.body.replayable,
            use_proxy_transport=request.use_proxy_transport,
            proxy_policy=request.proxy_policy.value,
            pool_timeout=request.timeouts.pool,
            read_timeout=request.timeouts.read,
            write_timeout=request.timeouts.write,
            total_timeout=request.timeouts.total,
            telemetry_request_id=telemetry_request_id,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    except AsyncFactoryProtocolError as exc:
        factory_error = exc.error
        factory_failed = True
    finally:
        await _close_body_async(body, factory_failed=factory_failed)
    raise factory_error


async def send_raw_stream_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
    telemetry_request_id: int | None = None,
    decode_content: bool = False,
) -> _foghttp.RawStreamResponse:
    body = prepare_async_upload_body(request.body, raw_client=raw_client)
    factory_failed = False
    try:
        return await raw_client.request_stream_async(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
            auth_override_headers=request.auth_override_headers,
            auth_removed_headers=request.auth_removed_headers,
            extensions=request.extensions,
            body=body.buffered_body,
            body_stream=body.raw_body,
            body_replayable=request.body.replayable,
            use_proxy_transport=request.use_proxy_transport,
            proxy_policy=request.proxy_policy.value,
            pool_timeout=request.timeouts.pool,
            read_timeout=request.timeouts.read,
            write_timeout=request.timeouts.write,
            total_timeout=request.timeouts.total,
            telemetry_request_id=telemetry_request_id,
            decode_content=decode_content,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    except AsyncFactoryProtocolError as exc:
        factory_error = exc.error
        factory_failed = True
    finally:
        await _close_body_async(body, factory_failed=factory_failed)
    raise factory_error


def _close_body(body: SyncUploadBody) -> None:
    active_error = sys.exception()
    try:
        body.close()
    except BaseException:
        if active_error is None:
            raise


async def _close_body_async(body: AsyncUploadBody, *, factory_failed: bool) -> None:
    active_error = sys.exception()
    try:
        await body.aclose()
    except asyncio.CancelledError:
        if active_error is None or factory_failed:
            raise
    except BaseException:
        if active_error is None and not factory_failed:
            raise
