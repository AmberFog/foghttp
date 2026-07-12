__all__ = (
    "RawRequestOptions",
    "send_raw_request",
    "send_raw_request_async",
    "send_raw_stream_request",
    "send_raw_stream_request_async",
)

from collections.abc import Sequence
from dataclasses import dataclass

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..._request_body import RequestBody
from ..._upload_body import prepare_async_upload_body, prepare_sync_upload_body
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


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawResponse:
    body = prepare_sync_upload_body(request.body)
    try:
        return raw_client.request(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
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
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        body.close()


def send_raw_stream_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawStreamResponse:
    body = prepare_sync_upload_body(request.body)
    try:
        return raw_client.request_stream(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
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
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        body.close()


async def send_raw_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawResponse:
    body = prepare_async_upload_body(request.body)
    try:
        return await raw_client.request_async(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
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
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        await body.aclose()


async def send_raw_stream_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawStreamResponse:
    body = prepare_async_upload_body(request.body)
    try:
        return await raw_client.request_stream_async(
            method=request.method.upper(),
            url=request.url,
            headers=request.headers,
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
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        await body.aclose()
