# Timeout Model

FogHTTP timeout settings are seconds as `float` values. The current timeout
model is intentionally documented for the buffered client that exists today.
Streaming bodies, mature read/write deadlines, and more specific timeout
exception classes are planned later.

```python
import foghttp


timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=0.5,
    total=10.0,
)

with foghttp.Client(timeouts=timeouts) as client:
    response = client.get("https://api.example.com/users")
    response.raise_for_status()
```

## Current Semantics

| Field | Default | Applies Today | Public Error |
|---|---:|---|---|
| `connect` | `2.0` | Client-level Rust connector TCP connect timeout. It is read when the lazy Rust transport is created from the client constructor settings. | No stable dedicated `ConnectTimeout` mapping yet; low-level connect failures can surface as `RequestError`, while the outer `total` deadline can raise `TimeoutError`. |
| `pool` | `1.0` | Waiting for a global or per-origin active request slot. | `PoolTimeout` for acquire timeout or full pending queue. |
| `total` | `30.0` | Outer deadline for acquiring a request slot and waiting for response headers for each transport hop. The same budget is shared across redirect hops. | Base `TimeoutError`. |
| `read` | `10.0` | Reserved for future response body read deadlines. | Not emitted separately today. |
| `write` | `10.0` | Reserved for future request body write deadlines. | Not emitted separately today. |

`PoolTimeout` is a subclass of `TimeoutError`. Catch `PoolTimeout` first when
application code wants to handle pool saturation differently from the broader
request deadline.

```python
try:
    response = client.get("https://api.example.com/users")
except foghttp.PoolTimeout:
    # The request could not acquire a transport slot in time.
    raise
except foghttp.TimeoutError:
    # The broader buffered transport deadline expired.
    raise
except foghttp.RequestError:
    # Network, protocol, DNS, TLS, or other transport failure.
    raise
```

Timeout exceptions expose a small structured diagnostic object when FogHTTP can
identify the timeout phase safely:

```python
try:
    client.get("https://api.example.com/slow")
except foghttp.TimeoutError as exc:
    if exc.diagnostic is not None:
        print(exc.phase)
        print(exc.origin)
        print(exc.elapsed, exc.timeout)
```

Current diagnostic phases are `pool_acquire`, `response_headers`, and
`response_body`; the exported `TimeoutPhase` type matches this current emitted
set. The `origin` field is normalized and never includes path, query, userinfo,
headers, or body data. `elapsed` and `timeout` are seconds, and `redirect_hop`
is zero-based.

## Client Defaults And Request Overrides

`Client(timeouts=...)` and `AsyncClient(timeouts=...)` define the default
timeouts for requests sent by that client.

Per-request `timeout=Timeouts(...)` currently affects only `pool` and `total`
for that request. It does not change the Rust connector's `connect` timeout,
and it does not activate separate `read` or `write` behavior.

```python
default_timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=1.0,
    total=30.0,
)

with foghttp.Client(timeouts=default_timeouts) as client:
    response = client.get(
        "https://api.example.com/fast",
        timeout=foghttp.Timeouts(
            pool=0.1,
            total=2.0,
        ),
    )
```

If a workload needs a different connector `connect` timeout, create a separate
client with that value in the constructor before the first request is sent.
FogHTTP creates the Rust transport lazily, but it still uses the client-level
constructor timeouts when that transport is created.

## Pool Timeout

`Timeouts.pool` controls how long a request may wait for FogHTTP's Rust-side
acquire gates:

- `Limits.max_active_requests` limits active buffered requests for the whole
  client.
- `Limits.max_active_requests_per_origin` optionally limits active buffered
  requests for one normalized origin.
- `Limits.max_pending_requests` limits how many requests may wait for an active
  slot.

If the pending queue is full, FogHTTP fails fast with `PoolTimeout` and the
message `request acquire queue is full`.

If a request waits longer than `Timeouts.pool` for a slot, FogHTTP raises
`PoolTimeout` with the message `request acquire timeout expired`.

Both cases increment `TransportStats.pool_acquire_timeouts`. Waiting requests
are not counted as `active_requests`. `PoolTimeout.diagnostic.phase` is
`pool_acquire`; the diagnostic `timeout` value is the configured pool timeout.

FogHTTP also records Rust-side acquire pressure metrics:

- `pool_acquire_attempts` counts acquire attempts for buffered request slots.
- `pool_acquire_immediate` counts successful acquires that did not enter the
  pending queue.
- `pool_acquire_waited` counts requests that entered the pending queue at least
  once.
- `peak_pending_requests` records the highest observed pending queue depth.
- `pool_acquire_wait_time_total_ns`, `pool_acquire_wait_time_max_ns`, and
  `pool_acquire_wait_time_last_ns` record completed wait intervals in
  nanoseconds.

These metrics describe request-slot pressure, not physical TCP connection
limits. `TransportStats` also exposes socket lifecycle diagnostics:
`connections_opened`, `connections_open_failed`, `connections_closed`,
`connections_reused`, `connections_aborted`, `active_connections`, and
`idle_connections`. `dump_transport_state()["origins"]` exposes the same
acquire-pressure and socket lifecycle fields per normalized origin, with
default ports omitted and non-default ports preserved, so a service can see
which upstream is holding active slots, opening sockets, reusing connections,
or building a pending queue without logging request paths or query strings.
FogHTTP also records buffered response body lifecycle counters. A clean
end-of-body increments either `response_body_reuse_eligible` or
`response_body_closed`, depending on whether the response is eligible for
keep-alive reuse. After response headers are received and buffered body
handling starts, timeout, cancellation, body transport error, memory budget
rejection, body-size rejection, and decoding failure increment
`response_body_aborted`. Errors before buffered body handling starts, such as
pool acquire or response-header failures, do not increment this body lifecycle
counter. These body counters describe Rust-side buffered body outcomes; socket
reuse is reported separately through `connections_reused`.
FogHTTP collects this transport-state snapshot in Rust and returns aggregate
and per-origin pressure through one raw client boundary call. The Rust snapshot
path retries briefly if current active/pending aggregate counters or
historical acquire-pressure counters are caught between matching per-origin
updates. Historical acquire counters are compared with per-origin sums only
while the origin registry still contains all historical origins; after idle
origin pruning, the per-origin history can be incomplete. The snapshot remains
diagnostic state rather than a lock-protected transport transaction.
Per-origin `last_activity_at_ns` is monotonic within the current transport
metrics lifetime and is not a wall-clock Unix timestamp.

For incident diagnostics, `dump_pool_diagnostics()` returns an on-demand snapshot
focused on current acquire waits: active holders, pending waiters, the oldest
pending wait age, whether another pending waiter can be admitted, and whether
progress is blocked by the global active request limit or the per-origin active
request limit. `blocked_by` is one of `none`, `global_active_requests`,
`per_origin_active_requests`, or `mixed`; `mixed` means current waiters are
blocked by more than one acquire limit. Origin keys are normalized origins only;
paths, queries, userinfo, headers, and bodies are not included.

```python
limits = foghttp.Limits(
    max_active_requests=10,
    max_active_requests_per_origin=5,
    max_pending_requests=100,
)
timeouts = foghttp.Timeouts(pool=0.2, total=5.0)

with foghttp.Client(limits=limits, timeouts=timeouts) as client:
    response = client.get("https://api.example.com/users")
    diagnostics = client.dump_pool_diagnostics()
```

## Total Timeout

`Timeouts.total` is the broader deadline for the current buffered transport
request path. Today it wraps:

- waiting for the acquire gate, together with `pool`
- waiting for response headers for the current hop
- collecting the buffered response body for the current hop
- redirect hops as one shared budget

If `total` expires while the request is waiting for a pool slot, `total` wins
and FogHTTP raises the base `TimeoutError`, not `PoolTimeout`. The same base
`TimeoutError` is raised when the shared total budget expires while reading the
buffered response body. `TimeoutError.diagnostic.phase` identifies whether the
deadline expired in `pool_acquire`, `response_headers`, or `response_body`; the
diagnostic `timeout` value is the configured total timeout.

```python
with foghttp.Client(timeouts=foghttp.Timeouts(pool=1.0, total=0.05)) as client:
    try:
        client.get("https://api.example.com/slow")
    except foghttp.TimeoutError:
        pass
```

`total` is a shared wall-clock budget, not a separate per-chunk read timeout.
For async callers that need an additional application-level budget, wrapping the
call in `asyncio.timeout()` is still fine; cancellation aborts the in-flight Rust
request.

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

## Connect Timeout

`Timeouts.connect` configures the Rust HTTP connector for the client transport.
It is a client-level setting:

```python
with foghttp.Client(
    timeouts=foghttp.Timeouts(
        connect=0.5,
        pool=1.0,
        total=5.0,
    ),
) as client:
    response = client.get("https://api.example.com/users")
```

Passing a different `connect` value in per-request `timeout=` does not rebuild
or reconfigure the connector. The current public error mapping also does not
guarantee a dedicated `ConnectTimeout` exception. Treat `Timeouts.total` as the
public request budget and `Timeouts.connect` as lower-level connector
configuration until the timeout exception split is expanded.

## Reserved Read And Write Timeouts

`Timeouts.read` and `Timeouts.write` exist to preserve the public shape of the
timeout model, but they are reserved today.

They do not yet provide:

- a per-chunk response body read deadline
- a request body upload write deadline
- dedicated `ReadTimeout` or write-specific exceptions

These fields will become meaningful with the streaming response/upload work.
Until then, use `Timeouts.total` as the shared buffered request deadline,
`Limits.max_response_body_size` to bound one buffered response, and
`Limits.max_buffered_response_bytes` to bound concurrent buffered response
memory.

## Buffered Body Limit

FogHTTP is buffered today, so responses are collected into memory before the
`Response` object is returned. To keep that safe by default, response memory is
limited at two levels:

- `Limits.max_response_body_size` protects one buffered response and defaults to
  `10 * 1024 * 1024` bytes.
- `Limits.max_buffered_response_bytes` protects aggregate in-flight buffered
  response bodies across concurrent requests and defaults to
  `100 * 1024 * 1024` bytes.

```python
limits = foghttp.Limits(
    max_response_body_size=2 * 1024 * 1024,
    max_buffered_response_bytes=32 * 1024 * 1024,
)
```

Passing `None` is an explicit opt-in to unbounded buffering for that level:

```python
limits = foghttp.Limits(
    max_response_body_size=None,
    max_buffered_response_bytes=None,
)
```

Use that only for controlled endpoints where another layer already enforces a
safe body size and aggregate memory budget. Large downloads should wait for
streaming responses.

The aggregate budget tracks in-flight buffered response bodies while Rust is
collecting them. Once a `Response` is returned, its Python `bytes` lifetime is
controlled by application code.

## Practical Defaults

For service-to-service JSON APIs, start with:

```python
timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=0.5,
    total=10.0,
)
```

Tune from there:

- lower `pool` when saturation should fail fast
- raise `pool` when short bursts should wait for capacity
- keep `total` larger than the expected upstream response time
- use a separate client when an upstream needs a different `connect` timeout
- keep `max_response_body_size` and `max_buffered_response_bytes` finite unless
  unbounded buffering is deliberate
