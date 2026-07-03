# Client Lifecycle

FogHTTP clients own transport resources once the first request is sent. This
includes the Rust client, connection pool state, request limits, and in-flight
async request handles. By default, clients use a shared Tokio runtime; a client
can opt into a dedicated runtime when isolation or worker-count tuning is
needed.

Use context managers by default. They make ownership explicit and ensure that
transport resources are released even when a request fails.

::: code-group

```python [Async]
import foghttp


async with foghttp.AsyncClient() as client:
    response = await client.get("https://api.example.com/users")
    response.raise_for_status()
```

```python [Sync]
import foghttp


with foghttp.Client() as client:
    response = client.get("https://api.example.com/users")
    response.raise_for_status()
```

:::

## Lazy Transport Creation

Constructing `Client` or `AsyncClient` does not create the Rust transport. The
transport is created lazily on the first `send()`, `stream()`, or shortcut
request such as `get()` or `post()`.

These operations do not create the Rust transport:

- constructing a client
- entering a context manager
- building a prepared `Request`
- calling `stats()` before the first request
- calling `dump_transport_state()` before the first request
- calling `dump_pool_diagnostics()` before the first request
- closing a never-used client

Before the first request, `stats()` returns an empty `TransportStats` value and
`dump_transport_state()` and `dump_pool_diagnostics()` return zero resource and
acquire-pressure counters.

```python
import foghttp


client = foghttp.Client()

assert client.stats() == foghttp.TransportStats()
assert client.dump_transport_state() == {
    "schema_version": 1,
    "snapshot_sequence": 0,
    "active_requests": 0,
    "pending_requests": 0,
    "peak_pending_requests": 0,
    "pool_acquire_attempts": 0,
    "pool_acquire_immediate": 0,
    "pool_acquire_waited": 0,
    "pool_acquire_timeouts": 0,
    "pool_acquire_wait_time_total_ns": 0,
    "pool_acquire_wait_time_max_ns": 0,
    "pool_acquire_wait_time_last_ns": 0,
    "response_body_reuse_eligible": 0,
    "response_body_closed": 0,
    "response_body_aborted": 0,
    "active_connections": 0,
    "idle_connections": 0,
    "connections_opened": 0,
    "connections_open_failed": 0,
    "connections_closed": 0,
    "connections_reused": 0,
    "connections_aborted": 0,
    "buffered_response_bytes": 0,
    "buffered_response_budget_rejections": 0,
    "origins": {},
}
assert client.dump_pool_diagnostics()["origins"] == {}

client.close()
```

## Runtime Ownership

By default, `Client` and `AsyncClient` use `runtime="shared"`. The shared Tokio
runtime is process-wide and initialized lazily by the first client that opens
transport state. Closing an individual client closes its Rust transport, pool
state, streams, request handles, and diagnostics, but does not shut down the
shared runtime used by other clients.

The shared runtime uses the detected process parallelism capped at `16` worker
threads. If parallelism cannot be detected, FogHTTP uses a conservative fallback
of `4` shared runtime workers. `runtime_workers` and `FOGHTTP_RUNTIME_WORKERS`
do not configure the shared runtime; use a dedicated runtime when a client needs
an explicit worker count.

Use `runtime="dedicated"` when a client needs runtime isolation:

```python
with foghttp.Client(runtime="dedicated") as client:
    response = client.get("https://api.example.com/users")
```

`runtime_workers=` is only valid for dedicated runtimes:

```python
with foghttp.Client(runtime="dedicated", runtime_workers=4) as client:
    response = client.get("https://api.example.com/users")
```

If `runtime=` is omitted and `runtime_workers` or `FOGHTTP_RUNTIME_WORKERS` is
set, FogHTTP selects `runtime="dedicated"` automatically. This preserves
worker-count tuning as a per-client contract and avoids hidden first-client-wins
configuration for the shared runtime.

Clients and runtime resources must not be shared across `fork()`. In pre-fork
servers or process pools, create FogHTTP clients after the worker process starts.

## Manual Close

If a context manager does not fit the application structure, close clients in a
`finally` block.

::: code-group

```python [Async]
import foghttp


client = foghttp.AsyncClient()
try:
    response = await client.get("https://api.example.com/users")
    response.raise_for_status()
finally:
    await client.aclose()
```

```python [Sync]
import foghttp


client = foghttp.Client()
try:
    response = client.get("https://api.example.com/users")
    response.raise_for_status()
finally:
    client.close()
```

:::

Calling `close()` or `aclose()` more than once is safe. A closed client cannot be
reopened; create a new client instead.

FogHTTP emits an `UnclosedClientError` resource warning if a client is garbage
collected while still open. Treat that warning as a last-resort safety net, not
as lifecycle management.

## Closed Client Behavior

After `close()` or `aclose()` starts, the client rejects new transport work.
Shortcut requests, `send()`, `stats()`, `dump_transport_state()`, and
`dump_pool_diagnostics()` raise `ClientClosedError`.

```python
import foghttp


client = foghttp.Client()
client.close()

try:
    client.get("https://api.example.com/users")
except foghttp.ClientClosedError:
    pass
```

`build_request()` is a pure request construction helper. It does not open the
transport by itself; only `send()`, `stream()`, or shortcut request methods use
transport state.

## Sync Close Semantics

For `Client`, `close()` is a graceful lifecycle barrier:

- new requests and transport stats calls are rejected immediately
- sync sends and stream entries already admitted by the client lifecycle are
  allowed to finish creating their response objects
- `close()` waits until those admitted in-flight sync transport entries complete
- the Rust transport is closed only after active sync entries finish
- active streamed response bodies are aborted by Rust transport shutdown
- concurrent `close()` calls wait for the same shutdown and return safely

This means `close()` can block while an already-admitted sync request is still
running. Configure request timeouts so shutdown cannot be held indefinitely by a
stalled upstream.

An admitted sync transport entry is a `send()` or `stream()` context enter that
passed the client lifecycle gate before shutdown started. Calls racing after
shutdown starts are rejected as new work.

```python
import foghttp


client = foghttp.Client(timeouts=foghttp.Timeouts(total=5.0))
try:
    response = client.get("https://api.example.com/slow")
    response.raise_for_status()
finally:
    client.close()
```

## Async Close And Cancellation

For `AsyncClient`, cancellation is part of the transport contract. If a Python
task waiting on a request is cancelled, FogHTTP aborts the in-flight Rust
request and releases the observed active request state.

```python
import asyncio

import foghttp


async with foghttp.AsyncClient() as client:
    try:
        async with asyncio.timeout(1.0):
            await client.get("https://api.example.com/slow")
    except TimeoutError:
        pass
```

Calling `aclose()` closes the async client for everyone using it, cancels
in-flight async requests, aborts active async streamed response bodies, and then
shuts down the Rust transport.

```python
import asyncio

import foghttp


client = foghttp.AsyncClient()
task = asyncio.create_task(client.get("https://api.example.com/slow"))
await asyncio.sleep(0)

await client.aclose()

try:
    await task
except asyncio.CancelledError:
    pass
```

Coordinate `aclose()` from the application owner of the client. Do not close a
shared async client from a request handler or worker task unless that task owns
the whole client lifecycle.

## Async Lifecycle Debug Mode

`AsyncClient` can enable opt-in lifecycle diagnostics for staging, tests, and
incident debugging:

```python
import foghttp


client = foghttp.AsyncClient(
    lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(),
)
try:
    response = await client.get("https://api.example.com/users")
    response.raise_for_status()

    snapshot = client.dump_lifecycle_debug()
    assert snapshot.active_request_count == 0
finally:
    await client.aclose()
```

The default client path does not track Python-level debug request handles.
`dump_lifecycle_debug()` is available even when `lifecycle_debug` is disabled.
In that case `snapshot.enabled` is `False`, Python-level active request handles
are empty, and the call does not create the lazy Rust transport by itself.

When `lifecycle_debug` is enabled, `dump_lifecycle_debug()` returns:

- active async request handles with method, mode, normalized origin, redacted
  URL, monotonic start time in nanoseconds, and age
- current Rust transport active and pending request-slot counts
- current pool acquire timeout count
- whether the client is already closed

Debug request URLs are redacted before they reach the snapshot. They never
include raw request bodies, response bodies, headers, userinfo, or unredacted
sensitive query values.

Buffered async requests stay visible until the response is returned or the
request fails. Streamed async requests stay visible until the streamed body
reaches EOF, the stream is closed, or the stream fails.

For pytest or staging checks, use strict mode or the explicit assertion helper:

```python
client = foghttp.AsyncClient(
    lifecycle_debug=foghttp.AsyncLifecycleDebugConfig(strict=True),
)

# Raises LifecycleError if active async handles or transport pressure remain.
client.assert_no_lifecycle_leaks()
```

With `strict=True`, `aclose()` still closes the Rust transport first, then raises
`LifecycleError` if shutdown started while debug-visible async work was active.
This is intended for tests and controlled diagnostics, not as normal production
shutdown behavior.

On normal `async with` exit, strict mode follows the same rule. If the context
body is already raising another exception, `__aexit__` still closes resources
but does not replace the original exception with a strict lifecycle error.

`assert_no_lifecycle_leaks()` checks both Python-level debug handles and current
Rust transport pressure. When debug mode is disabled, this helper can still be
used as a transport-pressure assertion, but it will not include Python-level
request descriptions.

If a debug-enabled async client is garbage collected while still open, the
`UnclosedClientError` warning includes lifecycle debug context such as active
debug request count and redacted active request descriptions. Treat this as a
last-resort diagnostic; the application owner should still use `async with` or
`await client.aclose()`.

## Sharing Clients

Reuse clients. Creating a client for every request prevents connection reuse and
creates extra Rust transport and pool state once requests start flowing. The
default shared runtime avoids per-client runtime threads, but it does not make
short-lived clients a good pooling strategy.

For sync code, `Client` is designed to be shared by multiple Python threads for
request sending. Lazy Rust transport creation is protected so concurrent first
requests share one transport instance.

For async code, share one `AsyncClient` between tasks that belong to the same
async application owner. Do not share one `AsyncClient` across different event
loops or treat it as a process-global singleton. Create one client per service
owner, worker, application lifespan, or other clear lifecycle boundary.

## Operational State

`TransportStats.active_requests` and `pending_requests` describe request slots
inside the current transport resource model. They are not physical TCP
connection counters.

- `schema_version` means the telemetry snapshot shape version
- `snapshot_sequence` is a monotonic sequence within the current Rust transport
  metrics lifetime; synthetic pre-transport stats use `0`
- `active_requests` means requests that acquired an active transport slot
- `pending_requests` means requests waiting for an active transport slot
- `peak_pending_requests` means the highest observed pending queue depth
- `pool_acquire_attempts` means requests that attempted to acquire a transport
  slot
- `pool_acquire_immediate` means successful acquires that did not wait
- `pool_acquire_waited` means requests that entered the pending queue at least
  once
- `pool_acquire_timeouts` means requests that timed out while waiting for a slot
- `pool_acquire_wait_time_total_ns`, `pool_acquire_wait_time_max_ns`, and
  `pool_acquire_wait_time_last_ns` describe completed acquire wait intervals in
  nanoseconds
- per-origin `last_activity_at_ns` is a monotonic timestamp in nanoseconds
  relative to the current transport metrics lifetime; it is not a Unix epoch
  timestamp
- `response_body_reuse_eligible` means response bodies that reached a clean
  end-of-body and had no response-level close signal
- `response_body_closed` means response bodies that reached a clean end-of-body
  but the response version or headers made the connection non-reusable
- `response_body_aborted` means response body handling ended before a clean
  success after response headers were received because of body-phase timeout,
  cancellation, body transport error, memory budget rejection, body-size
  rejection, decoding failure, or partial stream close
- `active_connections` means tracked physical connector I/O handles that were
  successfully opened and have not yet been dropped
- `idle_connections` means tracked connections that completed a reusable
  response and have not yet been observed serving another response or closing
- `connections_opened` means successful connector handoffs to Hyper after TCP
  and, for HTTPS, TLS setup
- `connections_open_failed` means connector failures before a usable transport
  was handed to Hyper
- `connections_closed` means tracked transport I/O handles dropped by Hyper
- `connections_reused` means a response was observed on a tracked connection
  after that same connection had already served an earlier response
- `connections_aborted` means a tracked connection saw wire response body
  collection abort after response headers were received
- `buffered_response_bytes` means bytes currently reserved for in-flight
  buffered response bodies before they are returned to Python
- `buffered_response_budget_rejections` means requests rejected by
  `Limits.max_buffered_response_bytes`

For buffered responses, the active request slot is released after the body has
been collected or aborted. For streamed responses, the active request slot is
held until the streamed body reaches EOF, the stream context is closed, the body
read is cancelled or aborted, or the client is closed.

The response body lifecycle counters describe FogHTTP's Rust-side body
contract for buffered and streamed response bodies. Socket lifecycle
counters describe tracked connector I/O lifecycle:
opened/closed are physical connector events, while reused/idle/aborted are
derived from responses observed on those tracked connections. `idle_connections`
is diagnostic state for the current HTTP/1 path, not a public promise about
Hyper's private pool internals.

Use `dump_transport_state()` for a small debug snapshot when active, pending,
acquire pressure, per-origin pressure, and buffered response budget state are
needed. The `origins` entry is keyed by normalized origin (`scheme://host`, with
`:port` only for non-default ports) and never includes path, query, userinfo,
headers, or body data.
The snapshot is collected by the Rust transport state layer in one raw boundary
call; Python only formats the already collected aggregate and per-origin data.
It includes `schema_version` and `snapshot_sequence`; the sequence is monotonic
within the current Rust transport lifetime and starts at `1` after transport
creation. Before the first request, FogHTTP returns a synthetic lazy snapshot
with `snapshot_sequence == 0`.
Rust also retries briefly when current active/pending request-slot counters or
historical acquire-pressure counters are caught between matching per-origin
updates. Historical acquire counters are compared with per-origin sums only
while the origin registry still contains all historical origins; after idle
origin pruning, the per-origin history can be incomplete. The snapshot is still
diagnostic state, not a lock-protected transaction over the transport.

```python
state = client.dump_transport_state()
api_pressure = state["origins"].get("https://api.example.com")
```

Use `dump_pool_diagnostics()` when the question is specifically why requests are
waiting for capacity. It reports the current pending queue, the oldest pending
wait age in nanoseconds, whether another pending waiter can be admitted, and
whether current waiters are blocked by the global active request limit, the
per-origin active request limit, or both.
Like transport state, this is a diagnostic snapshot with `schema_version` and a
Rust-side `snapshot_sequence`; it is useful for ordering incident observations,
not as a lock-protected SLA transaction.

```python
diagnostics = client.dump_pool_diagnostics()
if diagnostics["pending_requests"]:
    print(diagnostics["blocked_by"], diagnostics["oldest_pending_request_wait_ns"])
```

## Current Boundaries

The lifecycle contract currently applies to buffered requests/responses,
sync/async streamed response bodies, and streaming request bodies passed through
`content=`. Cookies and advanced auth helpers are planned later and may extend
the lifecycle model.

FogHTTP exposes socket lifecycle telemetry for the current HTTP/1 path, but
resource limits still describe request backpressure rather than strict raw TCP
connection caps.
