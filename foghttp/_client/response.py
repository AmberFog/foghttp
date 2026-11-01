__all__ = (
    "async_stream_response_from_raw",
    "response_from_raw",
    "stream_response_from_raw",
)

from collections.abc import Iterator
from contextlib import contextmanager
import time

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..headers import Headers
from ..request_extensions import RequestExtensions
from ..request_info import RequestInfo
from ..response import Response
from ..stream_response import AsyncStreamResponse, StreamResponse
from .retry import bind_retry_trace
from .retry_trace_mapping import retry_trace_from_raw


def request_info_from_raw(raw: _foghttp.RawRequestInfo, *, extensions: RequestExtensions) -> RequestInfo:
    headers = Headers(raw.headers)
    headers._mark_sensitive(raw.sensitive_headers)  # noqa: SLF001
    return RequestInfo(
        method=raw.method,
        url=raw.url,
        headers=headers,
        extensions=extensions,
    )


def response_from_raw(
    *,
    raw: _foghttp.RawResponse,
    started: float,
    extensions: RequestExtensions,
) -> Response:
    try:
        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        history = tuple(response_from_raw(raw=item, started=started, extensions=extensions) for item in raw.history)
        return bind_retry_trace(
            Response(
                status_code=raw.status_code,
                headers=Headers(raw.headers),
                content=raw.content,
                url=raw.url,
                request=request_info_from_raw(raw.request, extensions=extensions),
                http_version=raw.http_version,
                elapsed=elapsed,
                history=history,
            ),
            retry_trace_from_raw(raw),
        )
    finally:
        raw.release_buffered_body_reservations()


def stream_response_from_raw(
    *,
    raw: _foghttp.RawStreamResponse,
    started: float,
    extensions: RequestExtensions,
) -> StreamResponse:
    with _stream_response_conversion(raw) as raw_history:
        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        history = tuple(response_from_raw(raw=item, started=started, extensions=extensions) for item in raw_history)
        return bind_retry_trace(
            StreamResponse(
                status_code=raw.status_code,
                headers=Headers(raw.headers),
                url=raw.url,
                request=request_info_from_raw(raw.request, extensions=extensions),
                http_version=raw.http_version,
                elapsed=elapsed,
                _raw=raw,
                history=history,
            ),
            retry_trace_from_raw(raw),
        )


def async_stream_response_from_raw(
    *,
    raw: _foghttp.RawStreamResponse,
    started: float,
    extensions: RequestExtensions,
) -> AsyncStreamResponse:
    with _stream_response_conversion(raw) as raw_history:
        elapsed = raw.elapsed if raw.elapsed >= 0 else time.perf_counter() - started
        history = tuple(response_from_raw(raw=item, started=started, extensions=extensions) for item in raw_history)
        return bind_retry_trace(
            AsyncStreamResponse(
                status_code=raw.status_code,
                headers=Headers(raw.headers),
                url=raw.url,
                request=request_info_from_raw(raw.request, extensions=extensions),
                http_version=raw.http_version,
                elapsed=elapsed,
                _raw=raw,
                history=history,
            ),
            retry_trace_from_raw(raw),
        )


@contextmanager
def _stream_response_conversion(
    raw: _foghttp.RawStreamResponse,
) -> Iterator[list[_foghttp.RawResponse]]:
    history: list[_foghttp.RawResponse] = []
    try:
        history = raw.take_history()
        yield history
    except BaseException:
        raw.close()
        raise
    finally:
        for item in history:
            item.release_buffered_body_reservations()
