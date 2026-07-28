from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Literal

from prometheus_client import CollectorRegistry, Counter
from prometheus_client.openmetrics.exposition import generate_latest
import pytest

import foghttp
from foghttp.prometheus import PrometheusTelemetrySink


_ONE_SECOND_NS = 1_000_000_000
_TWO_SECONDS = 2
_THREE_SECONDS = 3
_HALF_SECOND = 0.5
_REPEATED_REQUEST_COUNT = 2
_CONCURRENT_ORIGIN_COUNT = 8
_CONCURRENT_ORIGIN_LIMIT = 2
_RESPONSE_BODY_BYTES = 2_048
_RETRY_ATTEMPTS = 2


def _request_event(
    *,
    origin: str | None = "https://api.example.test",
    method: str = "GET",
    status_code: int | None = 200,
    outcome: foghttp.TelemetryRequestOutcome = foghttp.TelemetryRequestOutcome.SUCCESS,
    error_type: str | None = None,
    request_elapsed_ns: int | None = None,
    response_body_bytes: int | None = None,
    retry_attempts: int | None = None,
    timeout_phase: foghttp.TimeoutPhase | None = None,
    redacted_url: str = "https://api.example.test/",
) -> foghttp.TelemetryEvent:
    return foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.REQUEST_FINISHED,
        event_sequence=1,
        observed_at_ns=1,
        request_id=1,
        mode=foghttp.TelemetryRequestMode.STREAM,
        method=method,
        origin=origin,
        redacted_url=redacted_url,
        status_code=status_code,
        outcome=outcome,
        error_type=error_type,
        request_elapsed_ns=request_elapsed_ns,
        response_body_bytes=response_body_bytes,
        retry_attempts=retry_attempts,
        timeout_phase=timeout_phase,
    )


def _retry_event(
    *,
    attempt: int,
    decision: foghttp.TelemetryRetryDecision,
    reason: foghttp.TelemetryRetryReason,
) -> foghttp.TelemetryEvent:
    return foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.RETRY_DECISION,
        event_sequence=1,
        observed_at_ns=1,
        request_id=1,
        mode=foghttp.TelemetryRequestMode.BUFFERED,
        method="GET",
        origin="https://api.example.test",
        redacted_url="https://api.example.test/",
        retry_attempt=attempt,
        retry_decision=decision,
        retry_reason=reason,
    )


def _metric_value(
    registry: CollectorRegistry,
    name: str,
    labels: dict[str, str],
) -> float | None:
    return registry.get_sample_value(name, labels)


def _sink_with_buckets(
    *,
    registry: CollectorRegistry,
    buckets: tuple[float, ...],
    target: Literal["stream", "pool"],
) -> PrometheusTelemetrySink:
    if target == "stream":
        return PrometheusTelemetrySink(
            registry=registry,
            stream_duration_buckets=buckets,
        )
    return PrometheusTelemetrySink(
        registry=registry,
        pool_wait_buckets=buckets,
    )


def test_terminal_request_maps_stable_labels_and_duration() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=2)

    sink.emit(
        _request_event(
            status_code=503,
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="ReadTimeout",
            request_elapsed_ns=2 * _ONE_SECOND_NS,
            response_body_bytes=_RESPONSE_BODY_BYTES,
            retry_attempts=_RETRY_ATTEMPTS,
            timeout_phase="response_body",
        ),
    )

    request_labels = {
        "method": "GET",
        "origin": "https://api.example.test",
        "status_class": "5xx",
        "outcome": "error",
    }
    failure_labels = {
        "method": "GET",
        "origin": "https://api.example.test",
        "status_class": "5xx",
        "error_class": "ReadTimeout",
    }
    duration_labels = {
        "method": "GET",
        "origin": "https://api.example.test",
        "outcome": "error",
    }
    timeout_labels = {
        "method": "GET",
        "origin": "https://api.example.test",
        "phase": "response_body",
    }

    assert _metric_value(registry, "foghttp_requests_total", request_labels) == 1
    assert _metric_value(registry, "foghttp_request_failures_total", failure_labels) == 1
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_count",
            duration_labels,
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_sum",
            duration_labels,
        )
        == _TWO_SECONDS
    )
    assert _metric_value(registry, "foghttp_timeouts_total", timeout_labels) == 1
    assert (
        _metric_value(
            registry,
            "foghttp_response_body_bytes_total",
            {
                "method": "GET",
                "origin": "https://api.example.test",
                "outcome": "error",
            },
        )
        == _RESPONSE_BODY_BYTES
    )
    assert (
        _metric_value(
            registry,
            "foghttp_retry_attempts_total",
            {
                "method": "GET",
                "origin": "https://api.example.test",
                "outcome": "error",
            },
        )
        == _RETRY_ATTEMPTS
    )


def test_body_and_pool_histograms_use_seconds() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)
    body_event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED,
        event_sequence=1,
        observed_at_ns=1,
        request_id=1,
        mode=foghttp.TelemetryRequestMode.STREAM,
        method="GET",
        origin="https://api.example.test",
        redacted_url="https://api.example.test/",
        status_code=200,
        outcome=foghttp.TelemetryRequestOutcome.SUCCESS,
        body_elapsed_ns=3 * _ONE_SECOND_NS,
    )
    acquire_event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
        event_sequence=2,
        observed_at_ns=2,
        request_id=1,
        mode=foghttp.TelemetryRequestMode.STREAM,
        method="GET",
        origin="https://api.example.test",
        redacted_url="https://api.example.test/",
        elapsed_ns=_ONE_SECOND_NS // 2,
        outcome=foghttp.TelemetryRequestOutcome.SUCCESS,
    )

    sink.emit(body_event)
    sink.emit(acquire_event)

    body_labels = {"method": "GET", "origin": "all", "outcome": "success"}
    assert (
        _metric_value(
            registry,
            "foghttp_stream_response_body_duration_seconds_sum",
            body_labels,
        )
        == _THREE_SECONDS
    )
    assert (
        _metric_value(
            registry,
            "foghttp_pool_acquire_wait_seconds_sum",
            {"outcome": "success"},
        )
        == _HALF_SECOND
    )


def test_labels_are_bounded_and_ignore_secret_bearing_event_fields() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=1)
    sensitive_value = "credential-material"

    sink.emit(
        _request_event(
            method="CUSTOM-METHOD",
            origin=(f"https://user:{sensitive_value}@first.example.test/private?token={sensitive_value}"),
            status_code=799,
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="DynamicallyGeneratedErrorClass",
            redacted_url=(f"https://user:{sensitive_value}@first.example.test/private?token={sensitive_value}"),
        ),
    )
    sink.emit(
        _request_event(
            origin="https://second.example.test",
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="RequestError",
        ),
    )

    payload = generate_latest(registry).decode()
    assert sensitive_value not in payload
    assert "/private" not in payload
    assert "second.example.test" not in payload
    assert 'method="OTHER"' in payload
    assert 'origin="https://first.example.test"' in payload
    assert 'origin="other"' in payload
    assert 'status_class="other"' in payload
    assert 'error_class="OtherError"' in payload


def test_missing_malformed_and_repeated_labels_remain_bounded() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=1)

    sink.emit(
        _request_event(
            origin=None,
            status_code=None,
            outcome=foghttp.TelemetryRequestOutcome.CANCELLED,
            error_type=None,
        ),
    )
    sink.emit(
        foghttp.TelemetryEvent(
            event_type=foghttp.TelemetryEventType.REQUEST_FINISHED,
            event_sequence=2,
            observed_at_ns=2,
            method=None,
            origin="\ud800",
            status_code=None,
            outcome=None,
        ),
    )
    sink.emit(_request_event(origin="https://repeat.example.test"))
    sink.emit(_request_event(origin="https://repeat.example.test"))

    assert (
        _metric_value(
            registry,
            "foghttp_request_failures_total",
            {
                "method": "GET",
                "origin": "unknown",
                "status_class": "none",
                "error_class": "none",
            },
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_requests_total",
            {
                "method": "OTHER",
                "origin": "unknown",
                "status_class": "none",
                "outcome": "unknown",
            },
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_requests_total",
            {
                "method": "GET",
                "origin": "https://repeat.example.test",
                "status_class": "2xx",
                "outcome": "success",
            },
        )
        == _REPEATED_REQUEST_COUNT
    )


def test_malformed_label_values_use_bounded_fallbacks() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=1)
    oversized_origin = f"https://{'.'.join(['a' * 63] * 9)}"

    sink.emit(
        _request_event(
            origin=oversized_origin,
            status_code="invalid",  # type: ignore[arg-type]
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type=[],  # type: ignore[arg-type]
        ),
    )
    sink.emit(
        _request_event(
            origin="https://accepted.example.test",
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="TimeoutError",
            timeout_phase=[],  # type: ignore[arg-type]
        ),
    )
    sink.emit(
        _request_event(
            origin="https://accepted.example.test",
            outcome=[],  # type: ignore[arg-type]
        ),
    )
    sink.emit(
        _retry_event(
            attempt=1.25,  # type: ignore[arg-type]
            decision=foghttp.TelemetryRetryDecision.STOP,
            reason=foghttp.TelemetryRetryReason.STATUS,
        ),
    )

    payload = generate_latest(registry).decode()
    assert oversized_origin not in payload
    assert 'origin="other"' in payload
    assert 'origin="https://accepted.example.test"' in payload
    assert 'status_class="other"' in payload
    assert 'error_class="OtherError"' in payload
    assert 'phase="unknown"' in payload
    assert 'attempt="unknown"' in payload
    assert 'outcome="unknown"' in payload


def test_concurrent_origin_admission_remains_bounded() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(
        registry=registry,
        origin_label_limit=_CONCURRENT_ORIGIN_LIMIT,
    )
    barrier = threading.Barrier(_CONCURRENT_ORIGIN_COUNT)

    def emit_request(origin_index: int) -> None:
        barrier.wait()
        sink.emit(
            _request_event(
                origin=f"https://origin-{origin_index}.example.test",
            ),
        )

    with ThreadPoolExecutor(max_workers=_CONCURRENT_ORIGIN_COUNT) as executor:
        tuple(executor.map(emit_request, range(_CONCURRENT_ORIGIN_COUNT)))

    request_family = next(family for family in registry.collect() if family.name == "foghttp_requests")
    request_samples = tuple(sample for sample in request_family.samples if sample.name == "foghttp_requests_total")
    observed_origins = {sample.labels["origin"] for sample in request_samples}
    admitted_origins = observed_origins - {"other"}

    assert sum(sample.value for sample in request_samples) == _CONCURRENT_ORIGIN_COUNT
    assert len(admitted_origins) == _CONCURRENT_ORIGIN_LIMIT
    assert "other" in observed_origins


def test_http_errors_are_not_transport_failures() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)

    sink.emit(_request_event(status_code=500))

    request_labels = {
        "method": "GET",
        "origin": "all",
        "status_class": "5xx",
        "outcome": "success",
    }
    assert _metric_value(registry, "foghttp_requests_total", request_labels) == 1
    assert next(iter(registry.collect())).name == "foghttp_requests"
    assert "foghttp_request_failures_total" not in generate_latest(registry).decode()


def test_retry_metrics_distinguish_decisions_from_scheduled_retries() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)
    sink.emit(
        _retry_event(
            attempt=12,
            decision=foghttp.TelemetryRetryDecision.RETRY,
            reason=foghttp.TelemetryRetryReason.NETWORK_ERROR,
        ),
    )
    sink.emit(
        _retry_event(
            attempt=2,
            decision=foghttp.TelemetryRetryDecision.STOP,
            reason=foghttp.TelemetryRetryReason.RETRIES_EXHAUSTED,
        ),
    )
    sink.emit(
        _retry_event(
            attempt=0,
            decision=foghttp.TelemetryRetryDecision.STOP,
            reason=foghttp.TelemetryRetryReason.STATUS,
        ),
    )

    common_labels = {"method": "GET", "origin": "all"}
    assert (
        _metric_value(
            registry,
            "foghttp_retry_decisions_total",
            {
                **common_labels,
                "attempt": "10+",
                "decision": "retry",
                "reason": "network_error",
            },
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_retry_decisions_total",
            {
                **common_labels,
                "attempt": "unknown",
                "decision": "stop",
                "reason": "status",
            },
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_retry_decisions_total",
            {
                **common_labels,
                "attempt": "2",
                "decision": "stop",
                "reason": "retries_exhausted",
            },
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_retries_scheduled_total",
            {**common_labels, "reason": "network_error"},
        )
        == 1
    )


@pytest.mark.parametrize(
    ("timeout_phase", "phase"),
    [
        pytest.param("connection_acquire", "connection_acquire", id="connection-acquire"),
        pytest.param("pool_acquire", "pool_acquire", id="pool-acquire"),
        pytest.param("request_body", "request_body", id="request-body"),
        pytest.param("retry_backoff", "retry_backoff", id="retry-backoff"),
        pytest.param("response_headers", "response_headers", id="response-headers"),
        pytest.param("response_body", "response_body", id="response-body"),
        pytest.param(None, "unknown", id="missing-diagnostic"),
    ],
)
def test_timeout_phase_uses_the_typed_terminal_diagnostic(
    timeout_phase: foghttp.TimeoutPhase | None,
    phase: str,
) -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)

    sink.emit(
        _request_event(
            status_code=None,
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="TimeoutError",
            timeout_phase=timeout_phase,
        ),
    )

    assert (
        _metric_value(
            registry,
            "foghttp_timeouts_total",
            {"method": "GET", "origin": "all", "phase": phase},
        )
        == 1
    )


def test_invalid_origin_label_limit_is_rejected() -> None:
    registry = CollectorRegistry()

    for invalid_limit in (-1, True, 1.5):
        with pytest.raises((TypeError, ValueError)):
            PrometheusTelemetrySink(
                registry=registry,
                origin_label_limit=invalid_limit,  # type: ignore[arg-type]
            )


def test_irrelevant_events_do_not_create_samples() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)
    event = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.REQUEST_STARTED,
        event_sequence=1,
        observed_at_ns=1,
    )
    acquire_without_duration = foghttp.TelemetryEvent(
        event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
        event_sequence=2,
        observed_at_ns=2,
    )

    sink.emit(event)
    sink.emit(acquire_without_duration)

    assert all(not tuple(family.samples) for family in registry.collect())


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(_request_event(request_elapsed_ns=-1), id="request-duration"),
        pytest.param(_request_event(response_body_bytes=-1), id="body-bytes"),
        pytest.param(_request_event(retry_attempts=-1), id="retry-attempts"),
        pytest.param(
            foghttp.TelemetryEvent(
                event_type=foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED,
                event_sequence=1,
                observed_at_ns=1,
                body_elapsed_ns=-1,
            ),
            id="body-duration",
        ),
        pytest.param(
            foghttp.TelemetryEvent(
                event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
                event_sequence=1,
                observed_at_ns=1,
                elapsed_ns=-1,
            ),
            id="pool-duration",
        ),
    ],
)
def test_negative_metric_value_is_rejected_without_partial_samples(
    event: foghttp.TelemetryEvent,
) -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry)

    with pytest.raises(ValueError, match="non-negative"):
        sink.emit(event)

    assert all(not tuple(family.samples) for family in registry.collect())


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(True, id="boolean"),
        pytest.param(1.5, id="fractional"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
    ],
)
def test_non_integer_metric_value_is_rejected_without_partial_samples(
    invalid_value: object,
) -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=1)
    event = _request_event(
        origin="https://rejected.example.test",
        request_elapsed_ns=invalid_value,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="non-negative integers"):
        sink.emit(event)

    assert all(not tuple(family.samples) for family in registry.collect())
    sink.emit(_request_event(origin="https://accepted.example.test"))
    assert 'origin="https://accepted.example.test"' in generate_latest(registry).decode()


def test_rejected_event_does_not_consume_origin_admission_capacity() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(registry=registry, origin_label_limit=1)

    with pytest.raises(ValueError, match="non-negative"):
        sink.emit(
            _request_event(
                origin="https://rejected.example.test",
                request_elapsed_ns=-1,
            ),
        )
    sink.emit(_request_event(origin="https://accepted.example.test"))

    labels = {
        "method": "GET",
        "origin": "https://accepted.example.test",
        "status_class": "2xx",
        "outcome": "success",
    }
    assert _metric_value(registry, "foghttp_requests_total", labels) == 1


def test_stream_duration_buckets_are_configurable_beyond_ten_seconds() -> None:
    registry = CollectorRegistry()
    sink = PrometheusTelemetrySink(
        registry=registry,
        stream_duration_buckets=(1.0, 10.0, 60.0),
        pool_wait_buckets=(1.0, 60.0),
    )

    sink.emit(_request_event(request_elapsed_ns=45 * _ONE_SECOND_NS))
    sink.emit(
        foghttp.TelemetryEvent(
            event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
            event_sequence=2,
            observed_at_ns=2,
            elapsed_ns=45 * _ONE_SECOND_NS,
            outcome=foghttp.TelemetryRequestOutcome.SUCCESS,
        ),
    )

    labels = {
        "method": "GET",
        "origin": "all",
        "outcome": "success",
    }
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_bucket",
            {**labels, "le": "10.0"},
        )
        == 0
    )
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_bucket",
            {**labels, "le": "60.0"},
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_pool_acquire_wait_seconds_bucket",
            {"outcome": "success", "le": "60.0"},
        )
        == 1
    )


@pytest.mark.parametrize(
    "invalid_buckets",
    [
        pytest.param((), id="empty"),
        pytest.param((-1.0,), id="negative"),
        pytest.param((1.0, 1.0), id="duplicate"),
        pytest.param((float("nan"),), id="nan"),
        pytest.param((float("inf"),), id="infinity"),
        pytest.param((True,), id="boolean"),
    ],
)
@pytest.mark.parametrize("target", ["stream", "pool"])
def test_invalid_bucket_config_does_not_partially_register_metrics(
    invalid_buckets: tuple[float, ...],
    target: Literal["stream", "pool"],
) -> None:
    registry = CollectorRegistry()

    with pytest.raises((TypeError, ValueError), match="strictly increasing order"):
        _sink_with_buckets(
            registry=registry,
            buckets=invalid_buckets,
            target=target,
        )

    assert tuple(registry.collect()) == ()
    PrometheusTelemetrySink(registry=registry)


def test_late_registry_collision_rolls_back_sink_metrics() -> None:
    registry = CollectorRegistry()
    existing = Counter(
        "foghttp_retries_scheduled_total",
        "Existing collector that collides with the final sink metric.",
        registry=registry,
    )

    with pytest.raises(ValueError, match="Duplicated timeseries"):
        PrometheusTelemetrySink(registry=registry)

    assert registry.get_sample_value("foghttp_requests_total") is None
    assert registry.get_sample_value("foghttp_retries_scheduled_total") == 0

    registry.unregister(existing)
    PrometheusTelemetrySink(registry=registry)


def test_bucket_sequences_are_snapshotted_for_every_labelset() -> None:
    registry = CollectorRegistry()
    stream_buckets = [1.0, 2.0]
    pool_buckets = [1.0, 2.0]
    sink = PrometheusTelemetrySink(
        registry=registry,
        stream_duration_buckets=stream_buckets,
        pool_wait_buckets=pool_buckets,
    )
    sink.emit(_request_event(request_elapsed_ns=_ONE_SECOND_NS))
    sink.emit(
        foghttp.TelemetryEvent(
            event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
            event_sequence=2,
            observed_at_ns=2,
            elapsed_ns=_ONE_SECOND_NS,
            outcome=foghttp.TelemetryRequestOutcome.SUCCESS,
        ),
    )

    stream_buckets[:] = [10.0, 20.0]
    pool_buckets[:] = [10.0, 20.0]
    sink.emit(
        _request_event(
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
            error_type="RequestError",
            request_elapsed_ns=_ONE_SECOND_NS,
        ),
    )
    sink.emit(
        foghttp.TelemetryEvent(
            event_type=foghttp.TelemetryEventType.POOL_ACQUIRE_FINISHED,
            event_sequence=3,
            observed_at_ns=3,
            elapsed_ns=_ONE_SECOND_NS,
            outcome=foghttp.TelemetryRequestOutcome.ERROR,
        ),
    )

    request_labels = {
        "method": "GET",
        "origin": "all",
        "outcome": "error",
    }
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_bucket",
            {**request_labels, "le": "2.0"},
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_stream_request_duration_seconds_bucket",
            {**request_labels, "le": "20.0"},
        )
        is None
    )
    assert (
        _metric_value(
            registry,
            "foghttp_pool_acquire_wait_seconds_bucket",
            {"outcome": "error", "le": "2.0"},
        )
        == 1
    )
    assert (
        _metric_value(
            registry,
            "foghttp_pool_acquire_wait_seconds_bucket",
            {"outcome": "error", "le": "20.0"},
        )
        is None
    )
