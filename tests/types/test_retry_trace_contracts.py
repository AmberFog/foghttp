from dataclasses import fields
from typing import assert_type

import foghttp
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK


def test_retry_trace_public_fields_are_explicit() -> None:
    assert tuple(field.name for field in fields(foghttp.RetryAttempt)) == (
        "attempt",
        "method",
        "origin",
        "redirect_hop",
        "status_code",
        "error_type",
        "decision",
        "reason",
        "backoff",
        "elapsed",
    )
    assert tuple(field.name for field in fields(foghttp.RetryTrace)) == (
        "attempts",
        "outcome",
        "status_code",
        "error_type",
        "elapsed",
    )


def _assert_retry_trace_access(
    response: foghttp.Response,
    stream_response: foghttp.StreamResponse,
    async_stream_response: foghttp.AsyncStreamResponse,
    error: foghttp.FogHTTPError,
) -> None:
    assert_type(response.retry_trace, foghttp.RetryTrace | None)
    assert_type(stream_response.retry_trace, foghttp.RetryTrace | None)
    assert_type(async_stream_response.retry_trace, foghttp.RetryTrace | None)
    assert_type(error.retry_trace, foghttp.RetryTrace | None)


def test_retry_trace_value_contracts() -> None:
    attempt = foghttp.RetryAttempt(
        attempt=1,
        method="GET",
        origin="origin",
        redirect_hop=0,
        status_code=SERVICE_UNAVAILABLE,
        error_type=None,
        decision=foghttp.TelemetryRetryDecision.RETRY,
        reason=foghttp.TelemetryRetryReason.STATUS,
        backoff=0.1,
        elapsed=0.2,
    )
    trace = foghttp.RetryTrace(
        attempts=(attempt,),
        outcome=foghttp.RetryTraceOutcome.RESPONSE,
        status_code=OK,
        error_type=None,
        elapsed=0.3,
    )

    assert_type(attempt.attempt, int)
    assert_type(attempt.method, str)
    assert_type(attempt.origin, str)
    assert_type(attempt.redirect_hop, int)
    assert_type(attempt.status_code, int | None)
    assert_type(attempt.error_type, str | None)
    assert_type(
        attempt.decision,
        foghttp.TelemetryRetryDecision | None,
    )
    assert_type(
        attempt.reason,
        foghttp.TelemetryRetryReason | None,
    )
    assert_type(attempt.backoff, float)
    assert_type(attempt.elapsed, float)
    assert_type(trace.attempts, tuple[foghttp.RetryAttempt, ...])
    assert_type(trace.outcome, foghttp.RetryTraceOutcome)
    assert_type(trace.status_code, int | None)
    assert_type(trace.error_type, str | None)
    assert_type(trace.elapsed, float)
