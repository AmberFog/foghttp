from collections.abc import Iterator
import time

import pytest

import foghttp
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.support.timeout_diagnostics import assert_timeout_diagnostic

from .assertions import retry_events, single_retry_event
from .constants import (
    ALWAYS_CLOSE_PATH,
    ALWAYS_STATUS_PATH,
    CLOSE_THEN_OK_PATH,
    EARLY_STATUS_THEN_OK_PATH,
    EXPECTED_ATTEMPTS,
    INCOMPLETE_RETRYABLE_RESPONSE_PATH,
    STATUS_THEN_OK_PATH,
)
from .server import RetryTestServer
from .sources import (
    CoordinatedReplayBodyFactory,
    FailingSyncBodyFactory,
    FailOnReplayBodyFactory,
    SyncBodyFactory,
    sync_chunks,
)


UPLOAD_FAILURE = "retry upload source failed"
REPLAY_FACTORY_FAILURE = "retry replay factory failed"
EXPECTED_REPLAY_BODY = b"second-attempt-body"
STALE_REPLAY_BODY = b"stale-first-attempt-body"
STALLED_PROVIDER_SLEEP = 0.05
RETRY_WRITE_TIMEOUT = 0.005
RETRY_TOTAL_TIMEOUT = 0.5


class ReplayFactoryFailure(RuntimeError):
    _retry_decisions: tuple[object, ...] = ()


def test_retry_is_opt_in(retry_server: RetryTestServer) -> None:
    with foghttp.Client() as client:
        response = client.get(retry_server.url + ALWAYS_STATUS_PATH)

    assert response.status_code == SERVICE_UNAVAILABLE
    assert len(retry_server.snapshot().requests_for(ALWAYS_STATUS_PATH)) == 1


def test_sync_retries_status_and_reuses_drained_connection(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.get(retry_server.url + STATUS_THEN_OK_PATH)
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    retry_event = single_retry_event(sink.events)
    assert response.status_code == OK
    assert response.content == b"ok"
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id == requests[1].connection_id
    assert stats.total_requests == 1
    assert stats.pool_acquire_attempts == EXPECTED_ATTEMPTS
    assert stats.response_body_reuse_eligible == EXPECTED_ATTEMPTS
    assert retry_event.retry_attempt == 1
    assert retry_event.status_code == SERVICE_UNAVAILABLE
    assert retry_event.retry_decision == foghttp.TelemetryRetryDecision.RETRY
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.STATUS
    assert retry_event.retry_backoff_ns == 0
    assert retry_event.origin == retry_server.url
    assert retry_event.redacted_url == retry_server.url
    assert retry_event.request_id == sink.events[-1].request_id
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.SUCCESS


def test_sync_retryable_response_drain_failure_does_not_retry(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(retry_server.url + INCOMPLETE_RETRYABLE_RESPONSE_PATH)
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    failed_requests = retry_server.snapshot().requests_for(INCOMPLETE_RETRYABLE_RESPONSE_PATH)
    recovery_requests = retry_server.snapshot().requests_for("/recovery")
    assert not isinstance(exc_info.value, foghttp.NetworkError)
    assert len(failed_requests) == 1
    assert recovery.status_code == OK
    assert failed_requests[0].connection_id != recovery_requests[0].connection_id
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_stream_retryable_response_drain_failure_does_not_retry(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        with (
            pytest.raises(foghttp.RequestError) as exc_info,
            client.stream(
                "GET",
                retry_server.url + INCOMPLETE_RETRYABLE_RESPONSE_PATH,
            ),
        ):
            pass
        recovery = client.get(retry_server.url + "/recovery")
        stats = client.stats()

    failed_requests = retry_server.snapshot().requests_for(INCOMPLETE_RETRYABLE_RESPONSE_PATH)
    recovery_requests = retry_server.snapshot().requests_for("/recovery")
    assert not isinstance(exc_info.value, foghttp.NetworkError)
    assert len(failed_requests) == 1
    assert recovery.status_code == OK
    assert failed_requests[0].connection_id != recovery_requests[0].connection_id
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_default_methods_do_not_retry_post(retry_server: RetryTestServer) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.post(retry_server.url + ALWAYS_STATUS_PATH, content=b"payload")

    requests = retry_server.snapshot().requests_for(ALWAYS_STATUS_PATH)
    retry_event = single_retry_event(sink.events)
    assert response.status_code == SERVICE_UNAVAILABLE
    assert len(requests) == 1
    assert retry_event.retry_decision == foghttp.TelemetryRetryDecision.STOP
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.METHOD_NOT_ALLOWED


def test_sync_explicit_methods_can_enable_post_retry(retry_server: RetryTestServer) -> None:
    policy = foghttp.RetryPolicy(
        retries=1,
        backoff=0,
        jitter=0,
        methods=("POST",),
    )

    with foghttp.Client(retry=policy) as client:
        response = client.post(
            retry_server.url + STATUS_THEN_OK_PATH,
            content=b"payload",
        )

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert tuple(request.body for request in requests) == (b"payload", b"payload")


def test_sync_exception_conditions_can_disable_network_retry(
    retry_server: RetryTestServer,
) -> None:
    conditions = foghttp.RetryConditions(exceptions=())
    policy = foghttp.RetryPolicy(
        retries=1,
        backoff=0,
        jitter=0,
        retry_on=conditions,
    )

    with (
        foghttp.Client(retry=policy) as client,
        pytest.raises(foghttp.NetworkError),
    ):
        client.get(retry_server.url + CLOSE_THEN_OK_PATH)

    assert len(retry_server.snapshot().requests_for(CLOSE_THEN_OK_PATH)) == 1


def test_sync_query_replays_factory_body(retry_server: RetryTestServer) -> None:
    content = SyncBodyFactory((b"replay", b"able"))
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.query(retry_server.url + STATUS_THEN_OK_PATH, content=content)

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == b"replayable"
    assert tuple(request.body for request in requests) == (b"replayable", b"replayable")
    assert content.calls == EXPECTED_ATTEMPTS


def test_sync_retry_isolates_replayable_upload_attempts_after_early_response(
    retry_server: RetryTestServer,
) -> None:
    content = CoordinatedReplayBodyFactory(EXPECTED_REPLAY_BODY, STALE_REPLAY_BODY)
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(retry=policy) as client:
        response = client.query(
            retry_server.url + EARLY_STATUS_THEN_OK_PATH,
            content=content,
        )

    requests = retry_server.snapshot().requests_for(EARLY_STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert response.content == EXPECTED_REPLAY_BODY
    assert tuple(request.body for request in requests) == (b"", EXPECTED_REPLAY_BODY)
    assert content.calls == EXPECTED_ATTEMPTS
    assert content.first_closed.wait(timeout=1.0)
    assert content.second_closed.wait(timeout=1.0)


def test_sync_query_blocks_non_replayable_body(retry_server: RetryTestServer) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.query(
            retry_server.url + ALWAYS_STATUS_PATH,
            content=sync_chunks((b"one-shot",)),
        )

    retry_event = single_retry_event(sink.events)
    assert response.status_code == SERVICE_UNAVAILABLE
    assert len(retry_server.snapshot().requests_for(ALWAYS_STATUS_PATH)) == 1
    assert retry_event.retry_decision == foghttp.TelemetryRetryDecision.BLOCK_NON_REPLAYABLE
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.NON_REPLAYABLE_BODY


def test_sync_does_not_retry_replayable_upload_source_failure(
    retry_server: RetryTestServer,
) -> None:
    content = FailingSyncBodyFactory(UPLOAD_FAILURE)
    policy = foghttp.RetryPolicy(retries=2, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        pytest.raises(foghttp.RequestError, match=UPLOAD_FAILURE) as exc_info,
    ):
        client.query(retry_server.url + "/upload-failure", content=content)

    assert not isinstance(exc_info.value, foghttp.NetworkError)
    assert content.calls == 1


def test_sync_does_not_retry_replayable_upload_write_timeout(
    retry_server: RetryTestServer,
) -> None:
    factory_calls = 0

    def body_factory() -> Iterator[bytes]:
        nonlocal factory_calls
        factory_calls += 1
        yield b"first"
        time.sleep(STALLED_PROVIDER_SLEEP)
        yield b"second"

    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)
    timeouts = foghttp.Timeouts(
        write=RETRY_WRITE_TIMEOUT,
        total=RETRY_TOTAL_TIMEOUT,
    )

    with (
        foghttp.Client(retry=policy, timeouts=timeouts) as client,
        pytest.raises(foghttp.WriteTimeout) as exc_info,
    ):
        client.query(
            retry_server.url + STATUS_THEN_OK_PATH,
            content=body_factory,
        )

    assert exc_info.value.phase == "request_body"
    assert factory_calls == 1


def test_sync_replay_factory_failure_preserves_prior_retry_telemetry(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    failure = ReplayFactoryFailure(REPLAY_FACTORY_FAILURE)
    content = FailOnReplayBodyFactory(failure)
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(
            retry=policy,
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        pytest.raises(RuntimeError, match=REPLAY_FACTORY_FAILURE),
    ):
        client.query(retry_server.url + STATUS_THEN_OK_PATH, content=content)

    retry_event = single_retry_event(sink.events)
    assert retry_event.retry_decision == foghttp.TelemetryRetryDecision.RETRY
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.STATUS
    assert sink.events[-1].outcome == foghttp.TelemetryRequestOutcome.ERROR
    assert sink.events[-1].error_type == type(failure).__name__
    assert content.calls == EXPECTED_ATTEMPTS


def test_sync_retries_pre_header_network_failure(retry_server: RetryTestServer) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.get(retry_server.url + CLOSE_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(CLOSE_THEN_OK_PATH)
    retry_event = single_retry_event(sink.events)
    assert response.status_code == OK
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id != requests[1].connection_id
    assert retry_event.error_type == "NetworkError"
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.NETWORK_ERROR


def test_sync_network_retry_exhaustion_preserves_error_and_recovers(
    retry_server: RetryTestServer,
) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with foghttp.Client(
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        with pytest.raises(foghttp.NetworkError):
            client.get(retry_server.url + ALWAYS_CLOSE_PATH)
        recovery = client.get(retry_server.url + "/recovery")

    decisions = retry_events(sink.events)
    assert recovery.status_code == OK
    assert len(retry_server.snapshot().requests_for(ALWAYS_CLOSE_PATH)) == EXPECTED_ATTEMPTS
    assert tuple(event.retry_decision for event in decisions) == (
        foghttp.TelemetryRetryDecision.RETRY,
        foghttp.TelemetryRetryDecision.STOP,
    )
    assert decisions[-1].retry_reason == foghttp.TelemetryRetryReason.RETRIES_EXHAUSTED
    request_failure = next(
        event
        for event in reversed(sink.events)
        if event.event_type == foghttp.TelemetryEventType.REQUEST_FINISHED
        and event.outcome == foghttp.TelemetryRequestOutcome.ERROR
    )
    assert request_failure.error_type == "NetworkError"


def test_sync_total_timeout_covers_retry_backoff(retry_server: RetryTestServer) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0.2, jitter=0)
    timeouts = foghttp.Timeouts(total=0.05)

    with (
        foghttp.Client(retry=policy, timeouts=timeouts) as client,
        pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info,
    ):
        client.get(retry_server.url + STATUS_THEN_OK_PATH)

    assert_timeout_diagnostic(
        exc_info.value,
        phase="retry_backoff",
        origin=retry_server.url,
        timeout=timeouts.total,
    )
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == 1


def test_sync_stream_retries_before_exposing_response(retry_server: RetryTestServer) -> None:
    sink = RecordingTelemetrySink()
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(
            retry=policy,
            telemetry=foghttp.TelemetryConfig(sink=sink),
        ) as client,
        client.stream("GET", retry_server.url + STATUS_THEN_OK_PATH) as response,
    ):
        content = b"".join(response.iter_bytes())

    retry_event = single_retry_event(sink.events)
    assert response.status_code == OK
    assert content == b"ok"
    assert len(retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)) == EXPECTED_ATTEMPTS
    assert retry_event.retry_decision == foghttp.TelemetryRetryDecision.RETRY
    assert retry_event.retry_reason == foghttp.TelemetryRetryReason.STATUS


def test_sync_stream_retries_pre_header_network_failure(
    retry_server: RetryTestServer,
) -> None:
    policy = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)

    with (
        foghttp.Client(retry=policy) as client,
        client.stream("GET", retry_server.url + CLOSE_THEN_OK_PATH) as response,
    ):
        content = b"".join(response.iter_bytes())

    requests = retry_server.snapshot().requests_for(CLOSE_THEN_OK_PATH)
    assert response.status_code == OK
    assert content == b"ok"
    assert len(requests) == EXPECTED_ATTEMPTS
    assert requests[0].connection_id != requests[1].connection_id


def test_sync_redirect_decision_precedes_matching_status_retry(
    sync_http_server: str,
) -> None:
    sink = RecordingTelemetrySink()
    conditions = foghttp.RetryConditions(
        statuses=(TEMPORARY_REDIRECT,),
        exceptions=(),
    )
    policy = foghttp.RetryPolicy(
        retries=1,
        backoff=0,
        jitter=0,
        retry_on=conditions,
    )

    with foghttp.Client(
        follow_redirects=True,
        retry=policy,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        response = client.get(f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}")

    assert response.status_code == OK
    assert len(response.history) == 1
    assert retry_events(sink.events) == ()
    assert any(event.event_type == foghttp.TelemetryEventType.REDIRECT_DECISION for event in sink.events)
