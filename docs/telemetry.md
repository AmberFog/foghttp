# Telemetry Contract

FogHTTP exposes two kinds of operational state today:

- `client.stats()` returns low-cardinality transport counters and gauges.
- `client.dump_transport_state()` and `client.dump_pool_diagnostics()` return
  diagnostic snapshots for incident debugging.

These APIs are intentionally not the same contract. `TransportStats` is the
current source for stable, low-cardinality operational counters. The `dump_*`
APIs are richer debugging views and include per-origin labels, queue details,
and pool pressure state that can change while requests are running.

## Snapshot Metadata

`TransportStats`, `dump_transport_state()`, and `dump_pool_diagnostics()`
include two contract fields:

| field | meaning |
| --- | --- |
| `schema_version` | Version of the telemetry snapshot shape. The current version is `1`. |
| `snapshot_sequence` | Monotonic Rust-side sequence for telemetry snapshots within one transport lifetime. |

The sequence starts at `1` after the Rust transport exists and increases across
`stats()` plus both diagnostic snapshot APIs for that client. Synthetic
pre-transport values returned before the first request use
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
| `pool_acquire_wait_time_total_ns`, `pool_acquire_wait_time_max_ns`, `pool_acquire_wait_time_last_ns` | cumulative total, max sample, last sample | Total and max are useful with care; last sample is diagnostic only. |
| `response_body_reuse_eligible`, `response_body_closed`, `response_body_aborted` | cumulative counters | Suitable for lifecycle rates and regression alerts. |
| `connections_opened`, `connections_open_failed`, `connections_closed`, `connections_reused`, `connections_aborted` | cumulative counters | Suitable for connection lifecycle rates. |
| `active_requests`, `pending_requests`, `active_connections`, `idle_connections`, `buffered_response_bytes` | current gauges | Suitable for capacity and saturation alerts. |
| `peak_pending_requests`, `buffered_response_budget_rejections` | peak gauge, cumulative counter | Useful for pressure and memory-budget alerting. |

`dump_transport_state()` adds per-origin copies of many of those values. The
aggregate and per-origin data are collected by Rust in one raw boundary call and
the Rust side retries briefly if aggregate pressure counters are caught between
matching per-origin updates. That makes the snapshot useful for debugging, but
it is still an eventually coherent diagnostic view.

Per-origin history can become incomplete after idle origin pruning. Per-origin
labels also carry cardinality risk, even though FogHTTP only exposes normalized
origins and never paths, queries, userinfo, headers, or bodies.

`dump_pool_diagnostics()` is even more intentionally diagnostic. It reports the
current pending waiters, oldest observed wait age, queue fullness, and blocking
reason at the time of the call. Use it to understand a stuck workload, not as a
strict SLA data source.

## Exporter Rules

Future Prometheus/OpenMetrics support must use only fields with suitable
guarantees:

- use `TransportStats` cumulative counters for rates
- use `TransportStats` current gauges for saturation and memory pressure
- keep per-origin labels opt-in and bounded
- redact or normalize labels before export
- avoid deriving alert-critical counters from `dump_transport_state()` retries
  or `dump_pool_diagnostics()` waiter snapshots
- benchmark exporter/versioning overhead before adding work to request hot paths

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
