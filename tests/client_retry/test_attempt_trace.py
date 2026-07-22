from dataclasses import FrozenInstanceError
import sys
from urllib.parse import urlencode

from faker import Faker
import pytest

import foghttp
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK
from tests.client_telemetry.models import RecordingTelemetrySink

from .assertions import require_retry_trace, single_retry_event
from .constants import (
    ALWAYS_CLOSE_PATH,
    ALWAYS_STATUS_PATH,
    EXPECTED_ATTEMPTS,
    STATUS_THEN_OK_PATH,
)
from .server import RetryTestServer
from .sources import sync_chunks


class RetryTracePropertyTrap:
    @property
    def retry_trace(self) -> None:
        msg = "HTTPStatusError must not inspect arbitrary response properties"
        raise AssertionError(msg)


class TraceAttachmentRejectingError(foghttp.RequestError):
    def __setattr__(self, name: str, value: object) -> None:
        if name == "_foghttp_retry_trace":
            msg = "retry trace attachment rejected"
            raise RuntimeError(msg)
        super().__setattr__(name, value)


def test_retry_trace_is_absent_without_opt_in_policy(retry_server: RetryTestServer) -> None:
    with foghttp.Client() as client:
        response = client.get(retry_server.url + ALWAYS_STATUS_PATH)

    assert response.retry_trace is None


def test_before_send_failure_records_pre_send_execution_attempt(
    retry_server: RetryTestServer,
) -> None:
    error = foghttp.RequestError("request rejected before send")

    def reject_request(_request: foghttp.TransportPolicyRequest) -> None:
        raise error

    hooks = foghttp.TransportPolicyHooks(before_send=reject_request)
    policy = foghttp.RetryPolicy(retries=0, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy, policy_hooks=hooks) as client,
        pytest.raises(foghttp.RequestError) as exc_info,
    ):
        client.get(retry_server.url)

    trace = require_retry_trace(exc_info.value)
    assert exc_info.value is error
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.status_code is None
    assert trace.error_type == foghttp.RequestError.__name__
    assert len(trace.attempts) == 1
    attempt = trace.attempts[0]
    assert attempt.attempt == 1
    assert attempt.method == "GET"
    assert attempt.origin == retry_server.url
    assert attempt.redirect_hop == 0
    assert attempt.status_code is None
    assert attempt.error_type == foghttp.RequestError.__name__
    assert attempt.decision is None
    assert attempt.reason is None
    assert attempt.backoff == 0
    assert attempt.decision_elapsed is None
    assert attempt.completed_elapsed == trace.elapsed
    assert retry_server.snapshot().requests == ()


def test_request_slot_rejection_records_pre_send_execution_attempt(
    retry_server: RetryTestServer,
) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)
    policy = foghttp.RetryPolicy(retries=0, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy, limits=limits) as client,
        pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full") as exc_info,
    ):
        client.get(retry_server.url)

    trace = require_retry_trace(exc_info.value)
    assert exc_info.value.phase == "pool_acquire"
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.status_code is None
    assert trace.error_type == foghttp.PoolTimeout.__name__
    assert len(trace.attempts) == 1
    attempt = trace.attempts[0]
    assert attempt.attempt == 1
    assert attempt.method == "GET"
    assert attempt.origin == retry_server.url
    assert attempt.redirect_hop == 0
    assert attempt.status_code is None
    assert attempt.error_type == foghttp.PoolTimeout.__name__
    assert attempt.decision is None
    assert attempt.reason is None
    assert attempt.backoff == 0
    assert attempt.decision_elapsed is None
    assert attempt.completed_elapsed == trace.elapsed
    assert retry_server.snapshot().requests == ()


def test_trace_attachment_failure_preserves_terminal_request_error(
    retry_server: RetryTestServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = TraceAttachmentRejectingError("request rejected")
    unraisable_errors: list[BaseException | None] = []

    def capture_unraisable(args: object) -> None:
        unraisable_errors.append(getattr(args, "exc_value", None))

    def reject_request(_request: foghttp.TransportPolicyRequest) -> None:
        raise error

    monkeypatch.setattr(sys, "unraisablehook", capture_unraisable)
    hooks = foghttp.TransportPolicyHooks(before_send=reject_request)

    with (
        foghttp.Client(retry=foghttp.RetryPolicy(), policy_hooks=hooks) as client,
        pytest.raises(TraceAttachmentRejectingError) as exc_info,
    ):
        client.get(retry_server.url)

    assert exc_info.value is error
    assert error.retry_trace is None
    assert len(unraisable_errors) == 1
    assert isinstance(unraisable_errors[0], RuntimeError)


def test_policy_error_after_retry_exposes_a_fresh_terminal_attempt(
    retry_server: RetryTestServer,
) -> None:
    hook_calls = 0
    error = foghttp.RequestError("second attempt rejected")

    def reject_second_attempt(_request: foghttp.TransportPolicyRequest) -> None:
        nonlocal hook_calls
        hook_calls += 1
        if hook_calls == EXPECTED_ATTEMPTS:
            raise error

    hooks = foghttp.TransportPolicyHooks(before_send=reject_second_attempt)
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy, policy_hooks=hooks) as client,
        pytest.raises(foghttp.RequestError) as exc_info,
    ):
        client.get(retry_server.url + STATUS_THEN_OK_PATH)

    trace = require_retry_trace(exc_info.value)
    retry_attempt, terminal_attempt = trace.attempts
    assert exc_info.value is error
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.error_type == foghttp.RequestError.__name__
    assert tuple(attempt.attempt for attempt in trace.attempts) == tuple(
        range(1, EXPECTED_ATTEMPTS + 1),
    )
    assert retry_attempt.status_code == SERVICE_UNAVAILABLE
    assert retry_attempt.decision == foghttp.TelemetryRetryDecision.RETRY
    assert terminal_attempt.attempt == EXPECTED_ATTEMPTS
    assert terminal_attempt.status_code is None
    assert terminal_attempt.error_type == foghttp.RequestError.__name__
    assert terminal_attempt.decision is None


def test_sync_status_retry_trace_is_ordered_bounded_redacted_and_matches_telemetry(
    retry_server: RetryTestServer,
    faker: Faker,
) -> None:
    query_secret = faker.pystr(min_chars=12, max_chars=24)
    header_secret = faker.pystr(min_chars=12, max_chars=24)
    body_secret = faker.pystr(min_chars=12, max_chars=24)
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.request(
            "GET",
            f"{retry_server.url}{STATUS_THEN_OK_PATH}?token={query_secret}",
            headers={"authorization": f"Bearer {header_secret}"},
            content=body_secret,
        )

    trace = require_retry_trace(response)
    retry_attempt, terminal_attempt = trace.attempts
    retry_event = single_retry_event(sink.events)
    assert trace.outcome == foghttp.RetryTraceOutcome.RESPONSE
    assert trace.status_code == OK
    assert trace.error_type is None
    assert len(trace.attempts) == policy.retries + 1
    assert retry_attempt == foghttp.RetryAttempt(
        attempt=1,
        method="GET",
        origin=retry_server.url,
        redirect_hop=0,
        status_code=SERVICE_UNAVAILABLE,
        error_type=None,
        decision=foghttp.TelemetryRetryDecision.RETRY,
        reason=foghttp.TelemetryRetryReason.STATUS,
        backoff=0.0,
        decision_elapsed=retry_attempt.decision_elapsed,
        completed_elapsed=retry_attempt.completed_elapsed,
    )
    assert terminal_attempt == foghttp.RetryAttempt(
        attempt=2,
        method="GET",
        origin=retry_server.url,
        redirect_hop=0,
        status_code=OK,
        error_type=None,
        decision=None,
        reason=None,
        backoff=0.0,
        decision_elapsed=None,
        completed_elapsed=terminal_attempt.completed_elapsed,
    )
    assert retry_attempt.decision_elapsed is not None
    assert retry_attempt.decision_elapsed == retry_attempt.completed_elapsed
    assert (
        0
        <= retry_attempt.decision_elapsed
        <= retry_attempt.completed_elapsed
        <= terminal_attempt.completed_elapsed
        <= trace.elapsed
    )
    assert retry_event.retry_attempt == retry_attempt.attempt
    assert retry_event.method == retry_attempt.method
    assert retry_event.origin == retry_attempt.origin
    assert retry_event.status_code == retry_attempt.status_code
    assert retry_event.error_type == retry_attempt.error_type
    assert retry_event.retry_decision == retry_attempt.decision
    assert retry_event.retry_reason == retry_attempt.reason
    assert retry_event.retry_backoff_ns == 0
    assert retry_event.elapsed_ns == round(retry_attempt.decision_elapsed * 1_000_000_000)
    assert query_secret not in repr(trace)
    assert header_secret not in repr(trace)
    assert body_secret not in repr(trace)
    assert STATUS_THEN_OK_PATH not in repr(trace)
    with pytest.raises(FrozenInstanceError):
        retry_attempt.completed_elapsed = 0.0
    with pytest.raises(FrozenInstanceError):
        trace.elapsed = 0.0


def test_sync_trace_preserves_typed_terminal_status_decisions(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.get(retry_server.url + ALWAYS_STATUS_PATH)

    trace = require_retry_trace(response)
    assert trace.outcome == foghttp.RetryTraceOutcome.RESPONSE
    assert trace.status_code == SERVICE_UNAVAILABLE
    assert tuple(attempt.decision for attempt in trace.attempts) == (
        foghttp.TelemetryRetryDecision.RETRY,
        foghttp.TelemetryRetryDecision.STOP,
    )
    assert tuple(attempt.reason for attempt in trace.attempts) == (
        foghttp.TelemetryRetryReason.STATUS,
        foghttp.TelemetryRetryReason.RETRIES_EXHAUSTED,
    )
    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()
    assert exc_info.value.retry_trace is trace


def test_sync_terminal_status_attempt_preserves_later_body_error(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=0, backoff=0, jitter=0)
    limits = foghttp.Limits(max_response_body_size=4)

    with (
        foghttp.Client(
            retry=policy,
            limits=limits,
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        pytest.raises(foghttp.ResponseBodyTooLargeError) as exc_info,
    ):
        client.get(retry_server.url + ALWAYS_STATUS_PATH)

    trace = require_retry_trace(exc_info.value)
    attempt = trace.attempts[0]
    retry_event = single_retry_event(sink.events)
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.error_type == foghttp.ResponseBodyTooLargeError.__name__
    assert trace.status_code is None
    assert len(trace.attempts) == 1
    assert attempt.status_code == SERVICE_UNAVAILABLE
    assert attempt.error_type == foghttp.ResponseBodyTooLargeError.__name__
    assert attempt.decision == foghttp.TelemetryRetryDecision.STOP
    assert attempt.reason == foghttp.TelemetryRetryReason.RETRIES_EXHAUSTED
    assert attempt.decision_elapsed is not None
    assert attempt.decision_elapsed <= attempt.completed_elapsed <= trace.elapsed
    assert retry_event.status_code == SERVICE_UNAVAILABLE
    assert retry_event.error_type is None
    assert retry_event.elapsed_ns == round(attempt.decision_elapsed * 1_000_000_000)


def test_http_status_error_does_not_inspect_arbitrary_response_properties() -> None:
    response = RetryTracePropertyTrap()

    error = foghttp.HTTPStatusError("status error", response=response)

    assert error.response is response
    assert error.retry_trace is None


def test_sync_trace_preserves_method_and_replayability_stop_reasons(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        method_response = client.post(
            retry_server.url + ALWAYS_STATUS_PATH,
            content=b"payload",
        )
        body_response = client.query(
            retry_server.url + ALWAYS_STATUS_PATH,
            content=sync_chunks((b"one-shot",)),
        )

    method_attempt = require_retry_trace(method_response).attempts[0]
    body_attempt = require_retry_trace(body_response).attempts[0]
    assert method_attempt.decision == foghttp.TelemetryRetryDecision.STOP
    assert method_attempt.reason == foghttp.TelemetryRetryReason.METHOD_NOT_ALLOWED
    assert body_attempt.decision == foghttp.TelemetryRetryDecision.BLOCK_NON_REPLAYABLE
    assert body_attempt.reason == foghttp.TelemetryRetryReason.NON_REPLAYABLE_BODY


def test_sync_network_exhaustion_trace_is_available_on_public_error(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        pytest.raises(foghttp.NetworkError) as exc_info,
    ):
        client.get(retry_server.url + ALWAYS_CLOSE_PATH)

    trace = require_retry_trace(exc_info.value)
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.status_code is None
    assert trace.error_type == foghttp.NetworkError.__name__
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)
    assert tuple(attempt.error_type for attempt in trace.attempts) == (
        foghttp.NetworkError.__name__,
        foghttp.NetworkError.__name__,
    )
    assert trace.attempts[-1].decision == foghttp.TelemetryRetryDecision.STOP
    assert trace.attempts[-1].reason == foghttp.TelemetryRetryReason.RETRIES_EXHAUSTED
    assert trace.attempts[0].decision == foghttp.TelemetryRetryDecision.RETRY
    assert trace.attempts[0].reason == foghttp.TelemetryRetryReason.NETWORK_ERROR


def test_sync_retry_trace_records_redirect_hop(
    sync_http_server: str,
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)
    target = retry_server.url + STATUS_THEN_OK_PATH
    query = urlencode({"status": TEMPORARY_REDIRECT, "location": target})

    with foghttp.Client(follow_redirects=True, retry=policy) as client:
        response = client.get(f"{sync_http_server}/redirect-to-location?{query}")

    trace = require_retry_trace(response)
    assert response.status_code == OK
    assert len(response.history) == 1
    assert tuple(attempt.redirect_hop for attempt in trace.attempts) == (1, 1)
    assert tuple(attempt.origin for attempt in trace.attempts) == (
        retry_server.url,
        retry_server.url,
    )


def test_sync_stream_exposes_retry_trace_after_headers(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        client.stream("GET", retry_server.url + STATUS_THEN_OK_PATH) as response,
    ):
        trace = require_retry_trace(response)
        content = b"".join(response.iter_bytes())

    assert trace.outcome == foghttp.RetryTraceOutcome.RESPONSE
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)
    assert content == b"ok"


def test_sync_stream_status_error_preserves_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        client.stream("GET", retry_server.url + ALWAYS_STATUS_PATH) as response,
    ):
        trace = require_retry_trace(response)
        with pytest.raises(foghttp.HTTPStatusError) as exc_info:
            response.raise_for_status()

    assert exc_info.value.retry_trace is trace


def test_sync_stream_terminal_error_exposes_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        pytest.raises(foghttp.NetworkError) as exc_info,
        client.stream("GET", retry_server.url + ALWAYS_CLOSE_PATH),
    ):
        pass

    trace = require_retry_trace(exc_info.value)
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.error_type == foghttp.NetworkError.__name__
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)


async def test_async_buffered_response_exposes_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        response = await client.get(retry_server.url + STATUS_THEN_OK_PATH)

    trace = require_retry_trace(response)
    assert trace.outcome == foghttp.RetryTraceOutcome.RESPONSE
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)


async def test_async_terminal_error_exposes_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            await client.get(retry_server.url + ALWAYS_CLOSE_PATH)

    trace = require_retry_trace(exc_info.value)
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.error_type == foghttp.NetworkError.__name__
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)


async def test_async_stream_exposes_retry_trace_after_headers(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with (
        foghttp.AsyncClient(retry=policy) as client,
        client.stream("GET", retry_server.url + STATUS_THEN_OK_PATH) as response,
    ):
        trace = require_retry_trace(response)
        content = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert trace.outcome == foghttp.RetryTraceOutcome.RESPONSE
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)
    assert content == b"ok"


async def test_async_stream_status_error_preserves_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with (
        foghttp.AsyncClient(retry=policy) as client,
        client.stream("GET", retry_server.url + ALWAYS_STATUS_PATH) as response,
    ):
        trace = require_retry_trace(response)
        with pytest.raises(foghttp.HTTPStatusError) as exc_info:
            response.raise_for_status()

    assert exc_info.value.retry_trace is trace


async def test_async_stream_terminal_error_exposes_retry_trace(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    async with foghttp.AsyncClient(retry=policy) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            async with client.stream("GET", retry_server.url + ALWAYS_CLOSE_PATH):
                pass

    trace = require_retry_trace(exc_info.value)
    assert trace.outcome == foghttp.RetryTraceOutcome.ERROR
    assert trace.error_type == foghttp.NetworkError.__name__
    assert tuple(attempt.attempt for attempt in trace.attempts) == (1, 2)
