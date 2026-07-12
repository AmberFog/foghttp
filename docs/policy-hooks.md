# Transport Policy Hooks

FogHTTP exposes a small opt-in Python edge around its Rust-owned transport
policy stages. It is intended for trusted, lightweight request admission and
response-head policy checks. It is not a middleware framework and does not
expose the internal transport adapter.

The default is `policy_hooks=None`. In that mode the Rust bridge does not
resolve callback or view objects, allocate hook snapshots, call Python, or
build a runtime list of policies. Built-in proxy and redirect policies remain
statically dispatched in Rust.

## Configuration

Hooks are configured per client and have the same contract for `Client` and
`AsyncClient`, including buffered and streaming requests:

```python
import foghttp


def allow_service_origins(request: foghttp.TransportPolicyRequest) -> None:
    if foghttp.URL(request.url).origin != "https://api.example.com":
        raise PermissionError("transport target is outside the service boundary")


def reject_server_errors(response: foghttp.TransportPolicyResponse) -> None:
    if response.status_code >= 500:
        raise RuntimeError("upstream response rejected by transport policy")


hooks = foghttp.TransportPolicyHooks(
    before_send=allow_service_origins,
    on_response_headers=reject_server_errors,
)

with foghttp.Client(policy_hooks=hooks) as client:
    response = client.get("https://api.example.com/resource")
```

All callbacks are synchronous and must return `None`. Raising an exception
rejects the current request and preserves that exception for the caller.
Returning any other value raises `TypeError`; hook return values cannot mutate
or replace transport state.

## Stage Order

| Hook | Ordering and scope |
|---|---|
| `before_send` | Runs for the initial request and every redirect hop after Rust has selected and validated the transport route, but before request-slot acquire. |
| `on_response_headers` | Runs for every response after Rust has classified any redirect action and before FogHTTP consumes or returns the response body. |
| `after_response_body` | Runs only for redirect response bodies consumed internally by FogHTTP. Rust first validates the redirect limit, replayability, scheme downgrade, header policy, and proxy boundary; the hook runs before the already validated mutation is applied. It does not run for the final body returned to the caller. |

There is deliberately no error, timeout, or cancellation hook. Those stages
remain unavailable until FogHTTP has a Rust-owned failure taxonomy and a real
retry-policy consumer.

## Snapshot Contract

`TransportPolicyRequest` is an immutable snapshot with:

- normalized uppercase `method`;
- full normalized `url`;
- `body` as `"empty"`, `"replayable"`, or `"non_replayable"`;
- zero-based `redirect_hop`;
- immutable request-scoped `extensions` supplied by the caller.

`TransportPolicyResponse` contains the request snapshot, `status_code`, and an
immutable tuple of response header pairs. Repeated values for the same header
retain their order.

The full URL and header values are available because trusted policy code may
need them to make a decision. They can contain credentials or tokens and are
not telemetry-safe data. Their `repr()` surfaces redact URL secrets and omit
header values plus extension keys and values, but hook code must still avoid
logging the raw attributes. Extensions are metadata only and are never
serialized into HTTP headers, the URL, or the request body. Use
[`TelemetryConfig`](./telemetry.md) when the goal is observability through
redacted events rather than request admission.

Snapshots contain no socket, permit, response body, cancellation handle, pool,
or runtime reference. Their transport fields are copies: replacing those fields
through Python escape hatches cannot alter the request or bypass Rust redirect
and replayability checks. The extensions mapping is immutable, but its values
are the caller-owned shallow references described in the request builder
contract.

## Execution And Lifecycle

Hooks run inline with transport policy evaluation. They may execute on FogHTTP
transport worker threads and may be invoked concurrently by concurrent
requests. A hook must therefore be fast, thread-safe, and independent of an
asyncio event loop, thread-local state, or `contextvars` propagation.
Extension values are shared shallow references, so hooks must treat them as
read-only and safe for concurrent observation.

Do not perform blocking I/O, call back into FogHTTP, or re-enter the same client
from a hook. Hook execution advances the wall clock used by later total-time
checks, but a running Python callback is not preempted or independently bounded
by FogHTTP timeouts. Callback failure unwinds through the normal request path
so permits, response bodies, connections, upload providers, and request metrics
retain their existing owners and cleanup behavior.

## Stability Boundary

`TransportPolicyHooks` and its immutable views are the deliberate public
surface. `src/core/policy/`, PyO3 bridge classes, raw clients, connector types,
and internal transport adapter Protocols remain implementation details and are
not extension points.
