__all__ = (
    "assert_early_upload_order",
    "assert_non_replayable_upload_trace",
    "assert_recovery_trace",
    "assert_replayed_upload_trace",
)

from itertools import pairwise

import foghttp
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK

from .assertions import RetryTraceSource, require_retry_trace
from .constants import EXPECTED_ATTEMPTS
from .server import RetryTestServer
from .sources import BlockedSyncBodySource, CoordinatedReplayBodyFactory


def assert_recovery_trace(response: foghttp.Response) -> None:
    trace = require_retry_trace(response)
    actual = (
        trace.outcome,
        trace.status_code,
        trace.error_type,
        tuple(
            (attempt.attempt, attempt.status_code, attempt.error_type, attempt.decision, attempt.reason)
            for attempt in trace.attempts
        ),
    )
    expected = (foghttp.RetryTraceOutcome.RESPONSE, OK, None, ((1, OK, None, None, None),))
    if actual != expected:
        raise AssertionError((actual, expected))


def assert_replayed_upload_trace(
    response: foghttp.Response,
    *,
    first_status_code: int | None = SERVICE_UNAVAILABLE,
    first_error_type: str | None = None,
) -> None:
    trace = require_retry_trace(response)
    expected_reason = (
        foghttp.TelemetryRetryReason.STATUS
        if first_status_code is not None
        else foghttp.TelemetryRetryReason.NETWORK_ERROR
    )
    actual = (
        trace.outcome,
        trace.status_code,
        trace.error_type,
        tuple(
            (attempt.attempt, attempt.status_code, attempt.error_type, attempt.decision, attempt.reason)
            for attempt in trace.attempts
        ),
    )
    expected = (
        foghttp.RetryTraceOutcome.RESPONSE,
        OK,
        None,
        (
            (1, first_status_code, first_error_type, foghttp.TelemetryRetryDecision.RETRY, expected_reason),
            (EXPECTED_ATTEMPTS, OK, None, None, None),
        ),
    )
    if actual != expected:
        raise AssertionError((actual, expected))


def assert_non_replayable_upload_trace(
    result: RetryTraceSource,
    *,
    status_code: int | None,
    error_type: str | None = None,
) -> None:
    trace = require_retry_trace(result)
    expected_outcome = foghttp.RetryTraceOutcome.RESPONSE if error_type is None else foghttp.RetryTraceOutcome.ERROR
    actual = (
        trace.outcome,
        trace.status_code,
        trace.error_type,
        tuple(
            (attempt.attempt, attempt.status_code, attempt.error_type, attempt.decision, attempt.reason)
            for attempt in trace.attempts
        ),
    )
    expected = (
        expected_outcome,
        status_code,
        error_type,
        (
            (
                1,
                status_code,
                error_type,
                foghttp.TelemetryRetryDecision.BLOCK_NON_REPLAYABLE,
                foghttp.TelemetryRetryReason.NON_REPLAYABLE_BODY,
            ),
        ),
    )
    if actual != expected:
        raise AssertionError((actual, expected))


def assert_early_upload_order(
    server: RetryTestServer,
    content: BlockedSyncBodySource | CoordinatedReplayBodyFactory,
    *,
    early_event: str = "early_status",
) -> None:
    snapshot = server.snapshot()
    if snapshot.early_upload_gate_error is not None or snapshot.early_upload_gate_passed is not True:
        raise AssertionError(snapshot)
    server_events = dict(snapshot.early_upload_events)
    source_events = dict(content.snapshot_events())
    ordered = [
        server_events["headers_received"],
        server_events["gate_wait_entered"],
        source_events["first_started"],
        source_events["first_waiting"],
        server_events[early_event],
    ]
    if isinstance(content, CoordinatedReplayBodyFactory):
        ordered.extend(
            (source_events["second_started"], source_events["stale_released"], source_events["first_closed"]),
        )
        if source_events["second_started"] >= source_events["second_closed"]:
            raise AssertionError(source_events)
    else:
        ordered.extend((source_events["release"], source_events["closed"]))
    if not all(first < second for first, second in pairwise(ordered)):
        raise AssertionError((server_events, source_events))
