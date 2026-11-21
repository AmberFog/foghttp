__all__ = ("assert_public_stream_history", "stream_resources_released")

import foghttp
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK

from .streaming_history_sources import StreamingHistoryServer


def assert_public_stream_history(
    response: foghttp.StreamResponse | foghttp.AsyncStreamResponse,
    server: StreamingHistoryServer,
) -> None:
    actual = (response.status_code, response.url, response.request.url, len(response.history))
    expected = (OK, server.final_url, server.final_url, len(server.history_bodies))
    if actual != expected:
        raise AssertionError((actual, expected))
    for hop, (item, body) in enumerate(zip(response.history, server.history_bodies, strict=True)):
        _assert_history_item(item, server, hop, body)
        if item.request.extensions is not response.request.extensions:
            msg = "history mapping lost request extension identity"
            raise AssertionError(msg)
        if item.http_version != response.http_version or item.elapsed < 0:
            raise AssertionError(item)
    _assert_stream_retry_trace(response, server)


def _assert_stream_retry_trace(
    response: foghttp.StreamResponse | foghttp.AsyncStreamResponse,
    server: StreamingHistoryServer,
) -> None:
    trace = response.retry_trace
    if trace is None:
        msg = "stream response lost its retry trace during history handoff"
        raise AssertionError(msg)
    attempt = trace.attempts[-1]
    actual_trace = (trace.outcome, attempt.redirect_hop, attempt.status_code, attempt.origin)
    expected_trace = (foghttp.RetryTraceOutcome.RESPONSE, len(server.history_bodies), response.status_code, server.url)
    if actual_trace != expected_trace:
        raise AssertionError((actual_trace, expected_trace))


def stream_resources_released(stats: foghttp.TransportStats) -> bool:
    return (
        stats.active_requests
        == stats.pending_requests
        == stats.buffered_response_bytes
        == stats.stream_decoder_reserved_bytes
        == 0
    )


def _assert_history_item(item: foghttp.Response, server: StreamingHistoryServer, hop: int, body: bytes) -> None:
    actual = (
        item.status_code,
        item.content,
        item.url,
        item.request.url,
        item.headers["location"],
        item.headers["x-history-hop"],
        item.headers["content-length"],
        item.request.method,
        item.request.headers["x-history-request"],
        dict(item.request.extensions),
        item.http_version,
        item.history,
    )
    expected = (
        FOUND,
        body,
        f"{server.url}/history/{hop}",
        f"{server.url}/history/{hop}",
        f"/history/{hop + 1}",
        str(hop),
        str(len(body)),
        "GET",
        "preserved",
        {"history-marker": "bound"},
        "HTTP/1.1",
        (),
    )
    if actual != expected:
        raise AssertionError((actual, expected))
