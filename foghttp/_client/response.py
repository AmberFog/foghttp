__all__ = ("response_from_raw",)

import time

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ..response import Response


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
        http_version=raw.http_version,
        elapsed=elapsed,
        history=history,
    )
