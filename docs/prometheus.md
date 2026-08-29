# Prometheus and OpenMetrics

FogHTTP provides an optional adapter for the official Python Prometheus client.
It maps typed `TelemetryEvent` values to labeled counters and histograms, and
maps alert-oriented `TransportStats` values to scrape-time gauges and counters.
It does not read `dump_transport_state()`, `dump_pool_diagnostics()`, or
`dump_proxy_diagnostics()`.

Install the optional dependency with FogHTTP:

```bash
pip install "foghttp[prometheus]"
```

## Configure a registry

Use an explicit registry and share one telemetry sink between every FogHTTP
client represented by that registry:

```python
from prometheus_client import CollectorRegistry

import foghttp
from foghttp.prometheus import (
    PrometheusTelemetrySink,
    PrometheusTransportStatsCollector,
)


registry = CollectorRegistry()
telemetry_sink = PrometheusTelemetrySink(registry=registry)
telemetry = foghttp.TelemetryConfig(
    sink=telemetry_sink,
    on_hook_error="warn",
)
client = foghttp.Client(telemetry=telemetry)

stats_collector = PrometheusTransportStatsCollector(client.stats)
registry.register(stats_collector)
```

`PrometheusTelemetrySink` implements the FogHTTP event-sink contract.
`PrometheusTransportStatsCollector` implements the native `prometheus_client`
custom collector contract. Keeping these roles separate makes registry
registration and resource ownership visible; there is no hidden global
registry or exporter lifecycle manager.

For multiple clients, pass every provider to one stats collector and share the
same event sink:

```python
stats_collector = PrometheusTransportStatsCollector(
    primary_client.stats,
    secondary_client.stats,
)
registry.register(stats_collector)
```

The collector sums gauges and cumulative counters across those clients. The
provider tuple is immutable. Keep all clients open while the collector is
registered, stop the scrape endpoint, unregister the collector, and only then
close the clients. A provider error fails that scrape instead of silently
serving stale data.

Stream lifetimes often exceed ordinary request-latency ranges. The defaults
cover stream durations through one hour and pool waits through one minute. Set
buckets to service-specific SLO boundaries when those ranges do not fit:

```python
telemetry_sink = PrometheusTelemetrySink(
    registry=registry,
    stream_duration_buckets=(0.1, 1.0, 10.0, 60.0, 300.0, 3_600.0),
    pool_wait_buckets=(0.001, 0.01, 0.1, 1.0, 5.0),
)
```

Both stream histograms share `stream_duration_buckets`; the pool acquire
histogram uses `pool_wait_buckets`. FogHTTP requires each sequence to contain
finite, non-negative, strictly increasing values. `prometheus_client` adds the
required positive-infinity bucket.

## Expose the registry

FogHTTP does not bundle a metrics server. Use the official Prometheus client
adapter that matches the service process.

For ASGI, mount the returned application at the service's metrics route:

```python
from prometheus_client import make_asgi_app


metrics_app = make_asgi_app(registry=registry)
# Framework-specific wiring: app.mount("/metrics", metrics_app)
```

For WSGI, mount `make_wsgi_app()` with the framework's dispatcher:

```python
from prometheus_client import make_wsgi_app


metrics_app = make_wsgi_app(registry=registry)
```

For a single service process, the official standalone server can expose the
same registry:

```python
from prometheus_client import start_http_server


server, metrics_thread = start_http_server(
    8000,
    addr="127.0.0.1",
    registry=registry,
)
try:
    run_service(client)
finally:
    server.shutdown()
    server.server_close()
    metrics_thread.join()
    registry.unregister(stats_collector)
    client.close()
```

The example binds to loopback intentionally. If a scrape endpoint must be
reachable over a network, place it behind the service's access-control and TLS
boundary rather than exposing the helper server directly.

FogHTTP does not currently support `prometheus_client` multiprocess mode for
either adapter. The stats adapter is a custom collector, which multiprocess
mode does not support. The event sink registers ordinary metrics in its
explicit registry, while multiprocess exposition requires a fresh registry
containing only `MultiProcessCollector`; combining the two can expose duplicate
series. Use one independently scraped registry per service process, or design
process aggregation at the application boundary. Do not pass a FogHTTP
registry to `MultiProcessCollector`.

## Metric contract

These primary metric names are the stable early-adopter contract. Official
`prometheus_client` counters may additionally expose their standard `_created`
series.

| Metric | Type and labels | Source and meaning |
| --- | --- | --- |
| `foghttp_requests_total` | counter: `method`, `origin`, `status_class`, `outcome` | Terminal `request_finished` events. HTTP 4xx/5xx responses retain `outcome="success"`; use `status_class` to classify HTTP responses. |
| `foghttp_request_failures_total` | counter: `method`, `origin`, `status_class`, `error_class` | Requests ending in `error` or `cancelled`, including validation and policy failures after telemetry starts. Intentional stream `closed` outcomes and HTTP error statuses are not failures. |
| `foghttp_response_body_bytes_total` | counter: `method`, `origin`, `outcome` | Final-response bytes read into FogHTTP's public body-consumption pipeline. Early stream close/error contributes only bytes already read from the native stream. A failure before a buffered `Response` is constructed, including a buffered-body read failure, contributes no sample. |
| `foghttp_retry_attempts_total` | counter: `method`, `origin`, `outcome` | Additional attempts that actually began after the initial attempt. A retry selected but cancelled during backoff is not counted. |
| `foghttp_stream_request_duration_seconds` | histogram: `method`, `origin`, `outcome` | Stream-only `request_elapsed_ns`, converted to seconds. |
| `foghttp_stream_response_body_duration_seconds` | histogram: `method`, `origin`, `outcome` | Stream-only `body_elapsed_ns`, converted to seconds. |
| `foghttp_pool_acquire_wait_seconds` | histogram: `outcome` | `pool_acquire_finished.elapsed_ns`, including immediate and queued acquire completions. Lower-level event delivery is best effort when the bounded native journal overflows. |
| `foghttp_timeouts_total` | counter: `method`, `origin`, `phase` | Terminal timeouts by typed phase: `connection_acquire`, `pool_acquire`, `request_body`, `retry_backoff`, `response_headers`, or `response_body`; missing diagnostics use `unknown`. |
| `foghttp_retry_decisions_total` | counter: `method`, `origin`, `attempt`, `decision`, `reason` | Typed retry decision records. Attempts above 10 use `attempt="10+"`. Terminal attempts without a decision do not emit this metric. |
| `foghttp_retries_scheduled_total` | counter: `method`, `origin`, `reason` | Delivered decisions that selected another retry. It measures scheduled retries, not proof that a later attempt began after backoff. Cancellation can abort the native task before its buffered decision records reach Python, so a retry selected immediately before a cancelled backoff may be absent. |
| `foghttp_active_requests` | gauge | Sum of current `TransportStats.active_requests`. |
| `foghttp_pending_requests` | gauge | Sum of current `TransportStats.pending_requests`. |
| `foghttp_pool_acquire_timeouts_total` | counter | Cumulative request-slot acquire timeouts from `TransportStats`. |
| `foghttp_connection_acquire_timeouts_total` | counter | Cumulative physical connection-slot acquire timeouts from `TransportStats`. |
| `foghttp_active_connections` | gauge | Sum of current active physical connections. |
| `foghttp_idle_connections` | gauge | Sum of current idle pooled connections. |
| `foghttp_connections_opened_total` | counter | Cumulative physical connections opened. |
| `foghttp_connection_open_failures_total` | counter | Cumulative physical connection open failures. |
| `foghttp_connections_closed_total` | counter | Cumulative physical connections closed. |
| `foghttp_connections_reused_total` | counter | Cumulative requests assigned an existing connection. |
| `foghttp_connections_aborted_total` | counter | Cumulative connections made non-reusable by abort or body failure. The typed contract has no separate `poisoned` state. |
| `foghttp_buffered_response_bytes` | gauge | Bytes currently reserved by buffered responses. This is resource pressure, distinct from delivered `foghttp_response_body_bytes_total`. |
| `foghttp_buffered_response_budget_rejections_total` | counter | Cumulative aggregate buffered-body budget rejections. |

`foghttp_response_body_bytes_total` is an API-boundary count, not a wire-byte
counter. Buffered responses contribute the decoded `response.content` length.
Streaming responses contribute bytes read into `iter_bytes()`, `iter_text()`,
or `iter_lines()`; streaming content-encoding decompression is not currently
available, and a text/line iterator may still buffer part of a chunk after the
native stream has been read. Use transport-level instrumentation when encoded
wire volume is the required quantity.

## Label safety and cardinality

The default `origin` label is the fixed value `all`. Enable per-origin series
only with an explicit positive bound:

```python
telemetry_sink = PrometheusTelemetrySink(
    registry=registry,
    origin_label_limit=20,
)
```

The first distinct normalized origins up to the limit retain their
`scheme://host[:port]` value. Later origins and normalized origins longer than
512 characters use `other`; malformed or missing origins use `unknown`.
Admission is thread-safe and has no eviction, so one process cannot relabel an
existing time series during its lifetime.

FogHTTP reparses the event origin before labeling it, removing userinfo, path,
query, and fragment. The exporter never reads `redacted_url`, headers, or body
content. Methods outside FogHTTP's stable method set use `OTHER`, status codes
use the fixed `1xx` through `5xx`, `none`, or `other` classes, and unknown error
classes use `OtherError`. These bounds keep attacker-controlled or custom
values from creating unbounded label sets.

Every unique label combination is still a separate time series. Keep
`origin_label_limit=0` unless per-origin operational queries justify the
additional cardinality.

## Alert and diagnostic boundary

`TransportStats` counters and gauges are the source for alert-oriented
capacity, memory, and connection series. Event-derived metrics exist only when
the telemetry sink is enabled and retain the typed hook contract's delivery
semantics. Production clients should normally use `on_hook_error="warn"` or
`"ignore"` so an exporter failure does not replace an HTTP result.

Diagnostic dump APIs are intentionally absent from both adapter signatures.
Their per-origin and waiter snapshots are eventually coherent debugging data,
not an SLA metric source. Use them during investigation, not to back recording
or alerting rules.
