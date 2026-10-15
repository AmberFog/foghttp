from contextlib import suppress
from typing import TYPE_CHECKING, Literal

from ..opentelemetry.span import RequestSpan


if TYPE_CHECKING:
    from ..opentelemetry import OpenTelemetryTracing
    from ..request import Request
    from ..stream_response import AsyncStreamResponse, StreamResponse
    from ..types import ResponseProtocol


def start_request_tracing(
    tracing: "OpenTelemetryTracing | None",
    request: "Request",
    *,
    mode: Literal["buffered", "stream"],
) -> RequestSpan | None:
    if tracing is None:
        return None
    return tracing._start(request, mode=mode)  # noqa: SLF001


def finish_request_tracing(
    span: RequestSpan | None,
    *,
    response: "ResponseProtocol | None" = None,
    error: BaseException | None = None,
) -> None:
    if span is not None:
        span.finish(status_code=None if response is None else response.status_code, error=error)


def finish_stream_tracing(span: RequestSpan | None, response: "StreamResponse | AsyncStreamResponse") -> None:
    try:
        finish_request_tracing(span, response=response)
    except BaseException:
        # Transport returned ownership, but instrumentation prevented handoff.
        with suppress(BaseException):
            response.close()
        raise
