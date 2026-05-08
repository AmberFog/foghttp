__all__ = ("response_from_raw",)

import time

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..request_info import RequestInfo
from ..response import Response


def request_info_from_raw(raw: _foghttp.RawRequestInfo) -> RequestInfo:
    return RequestInfo(
        method=raw.method,
        url=raw.url,
        headers=raw.headers,
    )


def response_from_raw(
    *,
    raw: _foghttp.RawResponse,
    started: float,
) -> Response:
    elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
    history = tuple(response_from_raw(raw=item, started=started) for item in raw.history)
    return Response(
        status_code=raw.status_code,
        headers=raw.headers,
        content=raw.content,
        url=raw.url,
        request=request_info_from_raw(raw.request),
        http_version=raw.http_version,
        elapsed=elapsed,
        history=history,
    )
