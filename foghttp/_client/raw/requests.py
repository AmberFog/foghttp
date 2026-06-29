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


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawResponse:
    body = prepare_sync_upload_body(request.body)
    try:
        return raw_client.request(
            request.method.upper(),
            request.url,
            request.headers,
            body.buffered_body,
            body.raw_body,
            request.body.replayable,
            request.use_proxy_transport,
            request.proxy_policy.value,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.write,
            request.timeouts.total,
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
            request.method.upper(),
            request.url,
            request.headers,
            body.buffered_body,
            body.raw_body,
            request.body.replayable,
            request.use_proxy_transport,
            request.proxy_policy.value,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.write,
            request.timeouts.total,
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
            request.method.upper(),
            request.url,
            request.headers,
            body.buffered_body,
            body.raw_body,
            request.body.replayable,
            request.use_proxy_transport,
            request.proxy_policy.value,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.write,
            request.timeouts.total,
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
            request.method.upper(),
            request.url,
            request.headers,
            body.buffered_body,
            body.raw_body,
            request.body.replayable,
            request.use_proxy_transport,
            request.proxy_policy.value,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.write,
            request.timeouts.total,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
    finally:
        await body.aclose()
