__all__ = ("response_from_raw", "stream_response_from_raw")

import time

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..headers import Headers
from ..request_info import RequestInfo
from ..response import Response
from ..stream_response import AsyncStreamResponse


def request_info_from_raw(raw: _foghttp.RawRequestInfo) -> RequestInfo:
    return RequestInfo(
        method=raw.method,
        url=raw.url,
        headers=Headers(raw.headers),
    )


def response_from_raw(
    *,
    raw: _foghttp.RawResponse,
    started: float,
) -> Response:
    try:
        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        history = tuple(response_from_raw(raw=item, started=started) for item in raw.history)
        return Response(
            status_code=raw.status_code,
            headers=Headers(raw.headers),
            content=raw.content,
            url=raw.url,
            request=request_info_from_raw(raw.request),
            http_version=raw.http_version,
            elapsed=elapsed,
            history=history,
        )
    finally:
        raw.release_buffered_body_reservations()


def stream_response_from_raw(
    *,
    raw: _foghttp.RawStreamResponse,
    started: float,
) -> AsyncStreamResponse:
    try:
        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        history = tuple(response_from_raw(raw=item, started=started) for item in raw.history)
        return AsyncStreamResponse(
            status_code=raw.status_code,
            headers=Headers(raw.headers),
            url=raw.url,
            request=request_info_from_raw(raw.request),
            http_version=raw.http_version,
            elapsed=elapsed,
            _raw=raw,
            history=history,
        )
    finally:
        raw.release_buffered_body_reservations()
