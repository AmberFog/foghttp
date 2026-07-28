__all__ = ("PrometheusTelemetrySink",)

from collections.abc import Sequence
import itertools
import math

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.registry import Collector

from ..telemetry import (
    TelemetryEvent,
    TelemetryEventType,
    TelemetryRequestOutcome,
    TelemetryRetryDecision,
)
from .labels import (
    OriginLabeler,
    enum_label,
    error_class_label,
    method_label,
    retry_attempt_label,
    status_class_label,
    timeout_phase_label,
)


_NANOSECONDS_PER_SECOND = 1_000_000_000
_DURATION_BUCKETS_REQUIRED = "duration buckets must contain finite non-negative numbers in strictly increasing order"
_METRIC_VALUE_REQUIRED = "telemetry metric values must be non-negative integers"
_DEFAULT_STREAM_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    300.0,
    900.0,
    3_600.0,
)
_DEFAULT_POOL_WAIT_BUCKETS = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)
_METHOD_LABEL = "method"
_ORIGIN_LABEL = "origin"
_STATUS_CLASS_LABEL = "status_class"
_OUTCOME_LABEL = "outcome"
_ERROR_CLASS_LABEL = "error_class"
_PHASE_LABEL = "phase"
_ATTEMPT_LABEL = "attempt"
_DECISION_LABEL = "decision"
_REASON_LABEL = "reason"
_REQUEST_LABELS = (
    _METHOD_LABEL,
    _ORIGIN_LABEL,
    _STATUS_CLASS_LABEL,
    _OUTCOME_LABEL,
)
_FAILURE_LABELS = (
    _METHOD_LABEL,
    _ORIGIN_LABEL,
    _STATUS_CLASS_LABEL,
    _ERROR_CLASS_LABEL,
)
_DURATION_LABELS = (_METHOD_LABEL, _ORIGIN_LABEL, _OUTCOME_LABEL)
_POOL_LABELS = (_OUTCOME_LABEL,)
_TIMEOUT_LABELS = (_METHOD_LABEL, _ORIGIN_LABEL, _PHASE_LABEL)
_RETRY_DECISION_LABELS = (
    _METHOD_LABEL,
    _ORIGIN_LABEL,
    _ATTEMPT_LABEL,
    _DECISION_LABEL,
    _REASON_LABEL,
)
_RETRY_SCHEDULED_LABELS = (_METHOD_LABEL, _ORIGIN_LABEL, _REASON_LABEL)
_FAILURE_OUTCOMES = (
    TelemetryRequestOutcome.ERROR,
    TelemetryRequestOutcome.CANCELLED,
)


class PrometheusTelemetrySink:
    """Map typed FogHTTP telemetry events to bounded Prometheus metrics."""

    def __init__(
        self,
        *,
        registry: CollectorRegistry,
        origin_label_limit: int = 0,
        stream_duration_buckets: Sequence[float] = _DEFAULT_STREAM_DURATION_BUCKETS,
        pool_wait_buckets: Sequence[float] = _DEFAULT_POOL_WAIT_BUCKETS,
    ) -> None:
        stream_duration_buckets = _duration_buckets(stream_duration_buckets)
        pool_wait_buckets = _duration_buckets(pool_wait_buckets)
        self._origins = OriginLabeler(origin_label_limit)
        self._requests = Counter(
            "foghttp_requests_total",
            "Completed FogHTTP logical requests.",
            _REQUEST_LABELS,
            registry=None,
        )
        self._request_failures = Counter(
            "foghttp_request_failures_total",
            "FogHTTP logical requests ending in error or cancellation.",
            _FAILURE_LABELS,
            registry=None,
        )
        self._response_body_bytes = Counter(
            "foghttp_response_body_bytes_total",
            "FogHTTP response-body bytes read into the public body-consumption pipeline.",
            _DURATION_LABELS,
            registry=None,
        )
        self._retry_attempts = Counter(
            "foghttp_retry_attempts_total",
            "FogHTTP additional request attempts that actually began.",
            _DURATION_LABELS,
            registry=None,
        )
        self._stream_request_duration = Histogram(
            "foghttp_stream_request_duration_seconds",
            "FogHTTP logical stream-request duration in seconds.",
            _DURATION_LABELS,
            buckets=stream_duration_buckets,
            registry=None,
        )
        self._stream_body_duration = Histogram(
            "foghttp_stream_response_body_duration_seconds",
            "FogHTTP stream response-body handoff duration in seconds.",
            _DURATION_LABELS,
            buckets=stream_duration_buckets,
            registry=None,
        )
        self._pool_acquire_wait = Histogram(
            "foghttp_pool_acquire_wait_seconds",
            "FogHTTP request-slot acquire duration in seconds.",
            _POOL_LABELS,
            buckets=pool_wait_buckets,
            registry=None,
        )
        self._timeouts = Counter(
            "foghttp_timeouts_total",
            "FogHTTP request timeouts grouped by public timeout class phase.",
            _TIMEOUT_LABELS,
            registry=None,
        )
        self._retry_decisions = Counter(
            "foghttp_retry_decisions_total",
            "FogHTTP retry policy decisions emitted for completed attempts.",
            _RETRY_DECISION_LABELS,
            registry=None,
        )
        self._retries_scheduled = Counter(
            "foghttp_retries_scheduled_total",
            "FogHTTP additional attempts selected by retry policy.",
            _RETRY_SCHEDULED_LABELS,
            registry=None,
        )
        _register_collectors(
            registry,
            (
                self._requests,
                self._request_failures,
                self._response_body_bytes,
                self._retry_attempts,
                self._stream_request_duration,
                self._stream_body_duration,
                self._pool_acquire_wait,
                self._timeouts,
                self._retry_decisions,
                self._retries_scheduled,
            ),
        )

    def emit(self, event: TelemetryEvent) -> None:
        if event.event_type is TelemetryEventType.REQUEST_FINISHED:
            self._observe_request(event)
            return
        if event.event_type is TelemetryEventType.RESPONSE_BODY_FINISHED:
            self._observe_stream_body(event)
            return
        if event.event_type is TelemetryEventType.POOL_ACQUIRE_FINISHED:
            self._observe_pool_acquire(event)
            return
        if event.event_type is TelemetryEventType.RETRY_DECISION:
            self._observe_retry_decision(event)

    def _observe_request(self, event: TelemetryEvent) -> None:
        _validate_request_metrics(event)
        method = method_label(event.method)
        status_class = status_class_label(event.status_code)
        outcome = enum_label(event.outcome)
        timeout_phase = timeout_phase_label(event.error_type, event.timeout_phase)
        origin = self._origins.label(event.origin)
        self._requests.labels(
            **{
                _METHOD_LABEL: method,
                _ORIGIN_LABEL: origin,
                _STATUS_CLASS_LABEL: status_class,
                _OUTCOME_LABEL: outcome,
            },
        ).inc()

        if event.outcome in _FAILURE_OUTCOMES:
            self._request_failures.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _STATUS_CLASS_LABEL: status_class,
                    _ERROR_CLASS_LABEL: error_class_label(event.error_type),
                },
            ).inc()

        if event.request_elapsed_ns is not None:
            self._stream_request_duration.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _OUTCOME_LABEL: outcome,
                },
            ).observe(_seconds(event.request_elapsed_ns))

        if event.response_body_bytes is not None:
            self._response_body_bytes.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _OUTCOME_LABEL: outcome,
                },
            ).inc(_non_negative(event.response_body_bytes))

        if event.retry_attempts is not None:
            self._retry_attempts.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _OUTCOME_LABEL: outcome,
                },
            ).inc(_non_negative(event.retry_attempts))

        if timeout_phase is not None:
            self._timeouts.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _PHASE_LABEL: timeout_phase,
                },
            ).inc()

    def _observe_stream_body(self, event: TelemetryEvent) -> None:
        if event.body_elapsed_ns is None:
            return
        duration_seconds = _seconds(event.body_elapsed_ns)
        self._stream_body_duration.labels(
            **{
                _METHOD_LABEL: method_label(event.method),
                _ORIGIN_LABEL: self._origins.label(event.origin),
                _OUTCOME_LABEL: enum_label(event.outcome),
            },
        ).observe(duration_seconds)

    def _observe_pool_acquire(self, event: TelemetryEvent) -> None:
        if event.elapsed_ns is None:
            return
        duration_seconds = _seconds(event.elapsed_ns)
        self._pool_acquire_wait.labels(
            **{_OUTCOME_LABEL: enum_label(event.outcome)},
        ).observe(duration_seconds)

    def _observe_retry_decision(self, event: TelemetryEvent) -> None:
        method = method_label(event.method)
        reason = enum_label(event.retry_reason)
        attempt = retry_attempt_label(event.retry_attempt)
        decision = enum_label(event.retry_decision)
        origin = self._origins.label(event.origin)
        self._retry_decisions.labels(
            **{
                _METHOD_LABEL: method,
                _ORIGIN_LABEL: origin,
                _ATTEMPT_LABEL: attempt,
                _DECISION_LABEL: decision,
                _REASON_LABEL: reason,
            },
        ).inc()
        if event.retry_decision is TelemetryRetryDecision.RETRY:
            self._retries_scheduled.labels(
                **{
                    _METHOD_LABEL: method,
                    _ORIGIN_LABEL: origin,
                    _REASON_LABEL: reason,
                },
            ).inc()


def _seconds(duration_ns: int) -> float:
    return _non_negative(duration_ns) / _NANOSECONDS_PER_SECOND


def _non_negative(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(_METRIC_VALUE_REQUIRED)
    return value


def _validate_request_metrics(event: TelemetryEvent) -> None:
    if event.request_elapsed_ns is not None:
        _seconds(event.request_elapsed_ns)
    if event.response_body_bytes is not None:
        _non_negative(event.response_body_bytes)
    if event.retry_attempts is not None:
        _non_negative(event.retry_attempts)


def _duration_buckets(buckets: Sequence[float]) -> tuple[float, ...]:
    normalized = tuple(_duration_bucket(bucket) for bucket in buckets)
    if not normalized:
        raise ValueError(_DURATION_BUCKETS_REQUIRED)
    if any(previous >= current for previous, current in itertools.pairwise(normalized)):
        raise ValueError(_DURATION_BUCKETS_REQUIRED)
    return normalized


def _duration_bucket(bucket: float) -> float:
    if isinstance(bucket, bool) or not isinstance(bucket, int | float):
        raise TypeError(_DURATION_BUCKETS_REQUIRED)
    value = float(bucket)
    if not math.isfinite(value) or value < 0:
        raise ValueError(_DURATION_BUCKETS_REQUIRED)
    return value


def _register_collectors(
    registry: CollectorRegistry,
    collectors: Sequence[Collector],
) -> None:
    registered: list[Collector] = []
    try:
        for collector in collectors:
            registry.register(collector)
            registered.append(collector)
    except Exception:
        for collector in reversed(registered):
            registry.unregister(collector)
        raise
