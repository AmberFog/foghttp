# Client Lifecycle

FogHTTP clients own transport resources once the first request is sent. This
includes the Rust client, the Tokio runtime used by that client, connection pool
state, request limits, and in-flight async request handles.

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
transport is created lazily on the first `send()` or shortcut request such as
`get()` or `post()`.

These operations do not create the Rust transport:

- constructing a client
- entering a context manager
- building a prepared `Request`
- calling `stats()` before the first request
- calling `dump_transport_state()` before the first request
- closing a never-used client

Before the first request, `stats()` returns an empty `TransportStats` value and
`dump_transport_state()` returns zero active and pending requests.

```python
import foghttp


client = foghttp.Client()

assert client.stats() == foghttp.TransportStats()
assert client.dump_transport_state() == {
    "active_requests": 0,
    "pending_requests": 0,
}

client.close()
```

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
Shortcut requests, `send()`, `stats()`, and `dump_transport_state()` raise
`ClientClosedError`.

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
transport by itself; only `send()` or shortcut request methods use transport
state.

## Sync Close Semantics

For `Client`, `close()` is a graceful lifecycle barrier:

- new requests and transport stats calls are rejected immediately
- requests that already entered `send()` are allowed to finish
- `close()` waits until those in-flight sync sends complete
- the Rust transport is closed only after active sync sends finish
- concurrent `close()` calls wait for the same shutdown and return safely

This means `close()` can block while an already-started sync request is still
running. Configure request timeouts so shutdown cannot be held indefinitely by a
stalled upstream.

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

Calling `aclose()` closes the async client for everyone using it and cancels
in-flight async requests before shutting down the Rust transport.

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

## Sharing Clients

Reuse clients. Creating a client for every request prevents connection reuse and
can create extra Rust runtime and pool state once requests start flowing.

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

- `active_requests` means requests that acquired an active transport slot
- `pending_requests` means requests waiting for an active transport slot
- `pool_acquire_timeouts` means requests that timed out while waiting for a slot

Use `dump_transport_state()` for a small debug snapshot when only active and
pending request counts are needed.

## Current Boundaries

The lifecycle contract currently applies to buffered requests and responses.
Streaming response bodies, streaming uploads, cookies, proxies, and advanced
auth helpers are planned later and may extend the lifecycle model.

FogHTTP does not expose true connection-level pool metrics yet. Until that lands,
resource stats intentionally describe request backpressure rather than raw TCP
connection accounting.
