# Telemetry Contract

FogHTTP exposes two kinds of operational state today:

- `client.stats()` returns low-cardinality transport counters and gauges.
- `client.dump_transport_state()` and `client.dump_pool_diagnostics()` return
  diagnostic snapshots for incident debugging.
- `telemetry=TelemetryConfig(...)` enables opt-in typed event hooks around
  request and response lifecycle phases.

These APIs are intentionally not the same contract. `TransportStats` is the
current source for stable, low-cardinality operational counters. The `dump_*`
APIs are richer debugging views and include per-origin labels, queue details,
and pool pressure state that can change while requests are running.

## Event Hooks

Event hooks are an observer API, not middleware. A hook receives immutable
`TelemetryEvent` values and must not be used to mutate requests, responses,
headers, redirects, retry policy, or resource cleanup.

```python
from foghttp import Client, TelemetryConfig, TelemetryEvent


class EventSink:
    def emit(self, event: TelemetryEvent) -> None:
        print(event.event_type, event.redacted_url, event.outcome)


with Client(telemetry=TelemetryConfig(sink=EventSink())) as client:
    response = client.get("https://api.example.com/items?token=secret")
```

The default path has no sink and does not allocate events. Python callbacks are
only invoked when `TelemetryConfig(sink=...)` is passed to a client.

Hooks run inline on the request path. For async clients this means the sink runs
on the event loop. Keep sinks fast and non-blocking; exporters that write to
files, sockets, queues, or tracing systems should enqueue compact redacted
events and do heavier work outside the request path.

For sync clients used concurrently from multiple threads, the same sink may be
called concurrently. `event_sequence` orders event creation inside the client
dispatcher; it is not a guarantee that a thread-safe sink will observe callbacks
arriving in list order.

Current event fields include:

| field | meaning |
| --- | --- |
| `schema_version` | Version of the telemetry event shape. The current version is `4`. |
| `event_sequence` | Monotonic Python-side sequence within the current client event dispatcher. |
| `observed_at_ns` | Monotonic observation timestamp, not Unix epoch. |
| `request_id` | Client-local id for request-scoped events; `None` for client-scoped lifecycle events. |
| `mode` | `buffered` or `stream` for request-scoped events. |
| `method`, `origin`, `redacted_url` | Safe request surface when applicable. URLs are redacted before they reach the hook. |
| `status_code`, `elapsed_ns`, `redirect_hop` | Response/redirect context when applicable. `elapsed_ns` keeps its existing header- or native-phase-oriented meaning and is always `None` on stream completion events. |
| `body_elapsed_ns` | Monotonic stream-body duration on `response_body_finished`; `None` on every other event and for buffered requests. |
| `request_elapsed_ns` | Monotonic logical stream-request duration on `request_finished`; `None` on every other event and for buffered requests. |
| `response_body_bytes` | Final-response bytes read into FogHTTP's public body-consumption pipeline. Buffered responses report decoded `response.content` bytes; streams report bytes read from the native stream before any buffering by text/line iterators. It is set on body/request completion events when a buffered `Response` exists or a stream is terminalized. Failures before a buffered `Response` is constructed, including buffered-body read failures, use `None`. |
| `retry_attempts` | Additional retry attempts that actually began after the initial attempt. It is set on `request_finished` when a completed `RetryTrace` is available. External cancellation may leave it `None`; a retry selected but not started during backoff is never counted. |
| `timeout_phase` | Typed `TimeoutDiagnostic.phase` on terminal timeout events when diagnostics are available; otherwise `None`. |
| `retry_attempt`, `retry_decision`, `retry_reason`, `retry_backoff_ns` | Structured opt-in retry decision context. Attempt numbering starts at `1`; backoff is a duration in nanoseconds. |
| `outcome`, `error_type` | Completion outcome and public error class name when applicable. |

FogHTTP never passes raw request or response bodies to telemetry hooks; only
the delivered response byte count is exposed. Hook
URLs are redacted with the same policy used by `repr()` and public error
messages. Headers are intentionally not included in the first event payload
shape; future header surfaces must be explicit and redacted.

### Streaming duration semantics

For an enabled streaming request, `request_elapsed_ns` starts when FogHTTP
creates the request telemetry context on entry to the client request path.
`body_elapsed_ns` starts later, when the successfully initialized stream is
bound for handoff to the caller after response-header telemetry has completed.
It therefore includes caller pauses and backpressure between body reads. An
explicit close before the first read still has a body duration measured from
that handoff.

These are logical wall-clock durations for the instrumented request, not
transport-only timings. Hooks run inline, so `request_elapsed_ns` includes hook
work that runs between its start and terminal boundaries. For a successfully
handed-off stream, this includes `request_started` plus any native, retry,
redirect, or response-header events delivered before body handoff.
`body_elapsed_ns` starts after those pre-handoff events and excludes their
delivery time. Neither duration includes terminal completion callbacks.
Consequently, `request_elapsed_ns - body_elapsed_ns` is not a network or
response-header latency measurement.

Both intervals end at the same monotonic terminal instant. FogHTTP records it
after clean EOF or after close/cancel has terminalized stream ownership,
released request accounting, and requested cancellation of any in-flight read.
The cancelled Tokio task may finish aborting asynchronously after that instant.
The timestamp is captured before lifecycle diagnostics, native event draining,
or completion sink callbacks run. The first terminal state wins:

| situation | completion outcome | `error_type` |
| --- | --- | --- |
| Clean EOF | `success` | `None` |
| Explicit close, early context exit, or ordinary application exception inside a stream block | `closed` | `None` |
| `asyncio.CancelledError` escaping an async stream block | `cancelled` | `CancelledError` |
| Cancellation of a pending async body read | `cancelled` | `CancelledError` |
| Read timeout or another body transport failure | `error` | Public FogHTTP error class |

Application exceptions and cancellations still propagate to the caller; this
table describes the stream terminal telemetry classification.

If a streaming request fails before response headers and no body is handed to
the caller, FogHTTP emits `request_finished` but no `response_body_finished`:
`request_elapsed_ns` is set while body duration is unavailable. Request-start
and applicable native lifecycle events are still delivered. These durations
are not Unix timestamps and are not defined as a sum of response-header
`elapsed_ns` and body time; their start boundaries intentionally describe
different lifecycle scopes.

`TelemetryConfig.on_hook_error` controls sink failures. The default is `raise`
so development and tests catch broken hooks early. Production exporters usually
should use `warn` or `ignore` so telemetry failures do not break outbound HTTP
requests.

| value | behavior |
| --- | --- |
| `raise` | raise `TelemetryHookError` from the failing sink exception |
| `warn` | emit a `RuntimeWarning` and keep the request running |
| `ignore` | suppress sink failures |

If a request is already failing because of transport, timeout, cancellation, or
stream cleanup, telemetry cleanup errors are suppressed so the original request
failure is not masked.

## Structured debug logging

`StructuredLoggingTelemetrySink` projects selected lifecycle events onto the
standard-library logger named `foghttp.lifecycle` at `DEBUG` level. FogHTTP does
not install handlers, configure the root logger, or enable the sink implicitly.
Applications opt in through the existing telemetry contract:

```python
import logging

from foghttp import Client, StructuredLoggingTelemetrySink, TelemetryConfig


logging.basicConfig(level=logging.DEBUG)
logging.getLogger("foghttp.lifecycle").setLevel(logging.DEBUG)

with Client(
    telemetry=TelemetryConfig(sink=StructuredLoggingTelemetrySink()),
) as client:
    client.get("https://api.example.com/items?token=secret")
```

The sink emits connection opened/open-failed/reused/closed/aborted events,
redirect and retry decisions, and terminal request events representing a
timeout. Other request, response-header, and body-completion events are not
logged by this adapter.

Every emitted `LogRecord` has the following `extra` attributes. Fields that do
not apply to an event are present with value `None`, so a formatter attached to
the dedicated logger can use a stable field set.

| field | meaning |
| --- | --- |
| `foghttp_event_type` | Typed lifecycle event name. |
| `foghttp_schema_version` | Telemetry event schema version. |
| `foghttp_event_sequence`, `foghttp_observed_at_ns` | Client-local ordering and monotonic observation time. |
| `foghttp_request_id`, `foghttp_mode`, `foghttp_method` | Request correlation fields when applicable. |
| `foghttp_origin` | Normalized scheme/host/port only; never userinfo, path, query, or fragment. |
| `foghttp_status_code`, `foghttp_elapsed_ns`, `foghttp_redirect_hop` | Response or lifecycle phase context when applicable. |
| `foghttp_retry_attempt`, `foghttp_retry_decision`, `foghttp_retry_reason`, `foghttp_retry_backoff_ns` | Retry decision context. |
| `foghttp_outcome`, `foghttp_error_type`, `foghttp_timeout_phase` | Terminal outcome and typed error/timeout context. |

The adapter deliberately does not copy `redacted_url`, headers, or body data
into log records. It normalizes `origin` again at the logging boundary, so raw
userinfo, path, query, and fragment data cannot cross through that field.

The default client path remains unchanged: without
`TelemetryConfig(sink=...)`, FogHTTP creates no telemetry events and makes no
logging calls. The sink also checks `Logger.isEnabledFor(DEBUG)` before building
structured fields. Once installed, however, telemetry callbacks and configured
logging handlers run inline on the request thread or event loop; keep handlers
fast or route records through application-owned non-blocking logging
infrastructure.

Pool acquire and connection lifecycle events are recorded in Rust when an
opt-in sink is configured. Rust never invokes the Python sink directly. It
writes compact records to a bounded, non-blocking client journal; Python drains
request-scoped records when their owning request or stream boundary returns or
raises. The same boundary also delivers client-scoped records already waiting
in the journal, while records owned by other requests remain queued. Stream
completion and close drain records produced while consuming the body, and
client close drains anything still pending. Native retry decisions retain
attempt order.

The native journal holds at most 4,096 pending or foreign-request records.
Producers never block when it is full. Delivering client-scoped records during
a request keeps ordinary connection churn from occupying the journal until
shutdown. A client-scoped sink failure under `raise` is deferred to client
close, so an unrelated request is not failed; `warn` and `ignore` retain their
configured behavior. A full client drain during close reports overflow through
the same policy. Request-scoped records forced out by client shutdown are still
delivered, but their hook failures are suppressed because cancellation or
cleanup remains the primary outcome.
Concurrent requests do not deliver each other's request-scoped records or
inherit each other's `raise` hook failures. Use `request_id` for correlation;
client-scoped callbacks and callbacks from concurrent request owners may still
execute on different threads.

Lower-level event semantics are:

| event | scope and fields |
| --- | --- |
| `pool_acquire_started` | Request-scoped start marker; `elapsed_ns` and `outcome` are `None`. |
| `pool_acquire_finished` | Request-scoped completion with acquire duration and `success`, `error`, or `cancelled` outcome. |
| `connection_opened` | Client-scoped successful physical connection acquisition/open with duration, including connection-cap wait. Hyper may begin a physical connection speculatively while a pooled connection is also eligible, so this event is intentionally not owned by a logical request. |
| `connection_open_failed` | Client-scoped failed or cancelled physical connection acquisition/open with duration and error context. |
| `connection_reused` | Request-scoped marker emitted when Hyper assigns an existing connection, before response headers arrive. |
| `connection_aborted` | Request-scoped non-reusable body/connection lifecycle outcome. Explicit close uses `closed` with no error; cancellation uses `cancelled` / `CancelledError`; known failures use `error` and the public error category. |
| `connection_closed` | Client-scoped close marker. `request_id`, `mode`, `method`, and `redirect_hop` are `None`; `origin` remains available. |

For native events, `elapsed_ns` is the Rust-measured duration of the represented
phase. `observed_at_ns` and `event_sequence` are assigned later by the Python
dispatcher, so they describe hook delivery rather than the original Rust event
time. Origins are normalized and omit path, query, fragment, and userinfo; no
headers or request/response body are included. The final
`request_finished.outcome` remains the logical request outcome.

## Snapshot Metadata

`TransportStats`, `dump_transport_state()`, and `dump_pool_diagnostics()`
include two contract fields:

| field | meaning |
| --- | --- |
| `schema_version` | Version of the telemetry snapshot shape. The current version is `4`. |
| `snapshot_sequence` | Monotonic Rust-side sequence for telemetry snapshots within one transport lifetime. |

The sequence starts at `1` after the Rust transport exists and increases across
`stats()` plus both diagnostic snapshot APIs for that client. It is unique until
the theoretical `u64::MAX` boundary; after that it saturates at `u64::MAX`.
Synthetic pre-transport values returned before the first request use
`snapshot_sequence == 0`; they preserve lazy transport creation and are not
emitted by Rust.

`snapshot_sequence` is useful for ordering observations from the same client.
It is not a wall-clock timestamp, not a Unix epoch, and not a full event stream
generation. Under concurrent callers it reflects Rust-side sequence assignment,
not necessarily the order in which Python calls return. For the `dump_*` APIs,
it also does not make the diagnostic snapshot a lock-protected transaction.

## Guarantees

`TransportStats` is the preferred source for alert-oriented telemetry because
its fields are direct Rust-side atomic counters and gauges. They are suitable
for low-cardinality operational monitoring when the field type is appropriate:

| field group | kind | alert/export guidance |
| --- | --- | --- |
| `schema_version`, `snapshot_sequence` | schema marker, monotonic sequence | Useful for parser compatibility and observation ordering. |
| `total_requests`, `failed_requests` | cumulative counters | Suitable for rates and error ratios. |
| `pool_acquire_attempts`, `pool_acquire_immediate`, `pool_acquire_waited`, `pool_acquire_timeouts` | cumulative counters | Suitable for rates and pressure indicators. |
| `pool_acquire_wait_time_total_ns`, `pool_acquire_wait_time_max_ns`, `pool_acquire_wait_time_last_ns` | cumulative total, max sample, last sample | Total and max are useful with care; last sample is diagnostic only and should not drive alerts. |
| `connection_acquire_attempts`, `connection_acquire_immediate`, `connection_acquire_waited`, `connection_acquire_timeouts` | cumulative counters | Suitable for physical connection-limit pressure indicators. |
| `connection_acquire_wait_time_total_ns`, `connection_acquire_wait_time_max_ns`, `connection_acquire_wait_time_last_ns` | cumulative total, max sample, last sample | Same interpretation as request-slot acquire wait timing, but for physical connection caps. |
| `response_body_reuse_eligible`, `response_body_closed`, `response_body_aborted` | cumulative counters | Suitable for lifecycle rates and regression alerts. |
| `connections_opened`, `connections_open_failed`, `connections_closed`, `connections_reused`, `connections_aborted`, `idle_timeout_evictions` | cumulative counters | Suitable for connection lifecycle rates. |
| `active_requests`, `pending_requests`, `active_connections`, `idle_connections`, `buffered_response_bytes` | current gauges | Suitable for capacity and saturation alerts. |
| `peak_pending_requests`, `buffered_response_budget_rejections` | peak gauge, cumulative counter | Useful for pressure and memory-budget alerting. |

`dump_transport_state()` adds per-origin copies of many of those values, plus
`last_used_at_ns`, `idle_age_ns`, and legacy `last_activity_at_ns`.
`last_used_at_ns` and `last_activity_at_ns` are monotonic timestamps relative to
the current Rust transport metrics lifetime, not Unix epoch timestamps.
`idle_age_ns` is `0` unless the origin currently has tracked idle connections;
otherwise it reports the current continuous idle-state age for that origin.
The aggregate and per-origin data are collected by Rust in one raw boundary call
and the Rust side retries briefly if aggregate pressure counters are caught
between matching per-origin updates. That makes the snapshot useful for
debugging, but it is still an eventually coherent diagnostic view.

Per-origin history can become incomplete after idle origin pruning. Per-origin
labels also carry cardinality risk, even though FogHTTP only exposes normalized
origins and never paths, queries, userinfo, headers, or bodies.

`dump_pool_diagnostics()` is even more intentionally diagnostic. It reports the
current pending waiters, oldest observed wait age, queue fullness, and blocking
reason at the time of the call. Use it to understand a stuck workload, not as a
strict SLA data source.

## Exporter Rules

The optional [Prometheus/OpenMetrics adapters](./prometheus.md) use only fields
with suitable guarantees:

- use `TransportStats` cumulative counters for rates
- use `TransportStats` current gauges for saturation and memory pressure
- keep per-origin labels opt-in and bounded
- redact or normalize labels before export
- treat `snapshot_sequence == 0` as a synthetic pre-transport snapshot that
  may be skipped for Rust-side telemetry streams
- avoid deriving alert-critical counters from `dump_transport_state()` retries
  or `dump_pool_diagnostics()` waiter snapshots
- keep exporter/versioning work outside the default request path

When stricter SLA-grade telemetry is needed, FogHTTP should add an event-derived
or versioned metrics source of truth in Rust rather than strengthening the
debug-only `dump_*` APIs by accident.

## Practical Guidance

Use `stats()` for dashboards and alerts. Use `dump_transport_state()` and
`dump_pool_diagnostics()` for investigation, incident snapshots, and local
debugging.

If an alert depends on exact transaction semantics across aggregate and
per-origin state, the current diagnostic snapshots are not the right source.
Track that as exporter or event-stream work instead of widening the diagnostic
contract.
