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

from ...timeouts import Timeouts
from .errors import raise_public_raw_error


@dataclass(frozen=True, slots=True)
class RawRequestOptions:
    method: str
    url: str
    headers: Sequence[tuple[str, str]]
    body: bytes | None
    body_replayable: bool
    use_http_proxy: bool
    timeouts: Timeouts


def send_raw_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawResponse:
    try:
        return raw_client.request(
            request.method.upper(),
            request.url,
            request.headers,
            request.body,
            request.body_replayable,
            request.use_http_proxy,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.total,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)


def send_raw_stream_request(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawStreamResponse:
    try:
        return raw_client.request_stream(
            request.method.upper(),
            request.url,
            request.headers,
            request.body,
            request.body_replayable,
            request.use_http_proxy,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.total,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)


async def send_raw_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawResponse:
    try:
        return await raw_client.request_async(
            request.method.upper(),
            request.url,
            request.headers,
            request.body,
            request.body_replayable,
            request.use_http_proxy,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.total,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)


async def send_raw_stream_request_async(
    *,
    raw_client: _foghttp.RawClient,
    request: RawRequestOptions,
) -> _foghttp.RawStreamResponse:
    try:
        return await raw_client.request_stream_async(
            request.method.upper(),
            request.url,
            request.headers,
            request.body,
            request.body_replayable,
            request.use_http_proxy,
            request.timeouts.pool,
            request.timeouts.read,
            request.timeouts.total,
        )
    except _foghttp.FogHttpError as exc:
        raise_public_raw_error(exc)
