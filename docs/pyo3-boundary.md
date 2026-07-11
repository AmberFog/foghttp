# PyO3 Boundary Notes

FogHTTP uses Rust and `hyper` for transport execution, while the public API is
Python-first. The Python/Rust boundary is therefore part of the resource
lifecycle contract, not just implementation detail.

These notes are for contributors changing `src/py/*`, streaming, cancellation,
runtime shutdown, close/aclose, or asyncio future integration.

## Core Rules

- Long Rust/Tokio work must run outside the GIL.
- Sync `runtime.block_on(...)` calls must be wrapped in `py.detach(...)`.
- Python objects may be stored as `Py<PyAny>`, but may only be bound or called
  while a GIL token is available.
- Tokio tasks must not mutate `asyncio.Future` objects directly from Rust worker
  threads.
- Future completion, exception, and cancellation must be scheduled through the
  owning event loop, normally with `loop.call_soon_threadsafe(...)`.
- Rust mutex guards must not live across `Python::attach(...)`, `bind(py)`,
  Python imports, `Py::new(...)`, `call_method*`, or Python callback
  scheduling.
- Cached `Py<...>` handles behind Rust locks must be taken or copied out before
  `clone_ref(py)` or other Python refcount operations.
- Close paths must abort active Rust tasks without waiting for task completion
  while holding the GIL.
- If raw close ever becomes blocking, `AsyncClient.aclose()` needs an
  async-safe shutdown path instead of doing blocking teardown on the event loop.

## Streaming Rules

Streaming adds repeated Python/Rust handoff, so it needs stricter review than
buffered requests:

- Sync body reads must not hold the GIL while waiting for the next network
  chunk.
- Async body reads must create Python futures under the GIL, then perform body
  reads on Rust/Tokio without holding the GIL.
- Body EOF, manual close, cancellation, timeout, transport error, and client
  close are different terminal states. Only clean EOF may look like successful
  completion.
- Partial read, cancellation, timeout, or manual close must not return a
  poisoned connection to reusable pool state.
- If a Rust stream state lock owns an active Python future handle, the lock must
  be released before scheduling cancellation or completion on the Python loop.

## Internal Request/Response Policy Seam

`src/core/policy/` is an internal, unstable seam for built-in transport
policies. It is not a public middleware API and does not expose Python hooks.
The default request path performs no Python callback, dynamic dispatch, or
policy-list allocation.

Policy stages run in this order:

1. Before send, the pipeline selects the direct or proxy transport for the
   normalized request URL.
2. After response headers, it may produce an opaque pending redirect decision.
3. After the redirect response body has been consumed, it validates the
   redirect limit, request-body replayability, and environment-derived proxy
   boundary before returning a typed request mutation.
4. `RequestState` applies the mutation before the next send. The policy layer
   never owns sockets, permits, response bodies, or Python objects.

The current mutation surface can replace the method and URL, remove request
headers, and either preserve or drop the request body. A non-replayable body is
never resent. Environment-derived proxy decisions are not reused across
origins and therefore fail closed until per-hop environment resolution exists.
Responses are observed through immutable status and header views; the current
seam does not mutate response status, headers, or body content.
Policy diagnostics may include a normalized origin, but must not include URL
userinfo, path, query parameters, or fragments.

Error and timeout policy stages are intentionally absent until the retry work
defines a Rust-owned failure taxonomy. Core policy code must not accept or
return `PyErr` merely to reserve a future hook.

## Review Checklist

For PRs touching PyO3, runtime, cancellation, close/aclose, streaming, or
transport state, check:

- Is any blocking operation performed while a `Python<'_>` token is alive?
- Does any code call `runtime.block_on(...)` without `py.detach(...)`?
- Does any Rust mutex guard cross a Python API call or callback scheduling?
- Can completion and cancellation race? If yes, is there a single-winner guard?
- Are Python futures completed or cancelled only on their owning event loop?
- Does close/aclose abort in-flight work without blocking the event loop?
- Are metrics and active/pending counters finished exactly once?
- Do tests prove cleanup for success, timeout, cancellation, manual close, and
  client close?

## Current Audit Scope

The current boundary audit checked these paths:

- `RawClient.request()` and `RawClient.request_stream()` release the GIL around
  synchronous `runtime.block_on(...)` waits.
- Async request and stream request spawning creates Python futures under the GIL
  and completes them from Tokio tasks through `call_soon_threadsafe(...)`.
- Async request and stream registries drain active handles before aborting or
  cancelling Python futures, so registry locks do not cross Python callback
  scheduling.
- Stream state transitions collect active read tasks under the Rust state lock,
  then cancel Python futures after releasing that lock.
- Streaming response cached future helpers keep Python refcount operations
  outside the Rust mutex that protects the cache.

## Regression Coverage

Boundary-sensitive tests should live near the behavior they protect:

- `tests/pyo3_boundary/` covers explicit GIL/PyO3 boundary regressions.
- `tests/client_cancellation/` covers request cancellation and pending acquire
  cleanup.
- `tests/client_lifecycle/` covers close/close race semantics.
- `tests/client_streaming/` covers stream cleanup, read timeout, and
  partial-read behavior.
- Rust unit tests under `src/py/client/**/tests.rs` cover internal state
  machines where Python integration is not required.
