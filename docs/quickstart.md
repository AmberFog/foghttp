# Getting Started

## Install for Development

Development requires a Rust toolchain with `cargo` available in `PATH`.

```bash
uv run --extra dev --with "maturin>=1.7,<2" maturin develop
```

Runtime requirements:

- Python `>=3.11`
- `orjson>=3.11,<4`

## Basic Request

::: code-group

```python [Async]
import asyncio

import foghttp


async def main() -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(
            "https://httpbin.org/get",
            params={"limit": 10},
        )

        response.raise_for_status()
        print(response.status_code)
        print(response.headers["content-type"])
        print(response.json())


asyncio.run(main())
```

```python [Sync]
import foghttp


with foghttp.Client() as client:
    response = client.get(
        "https://httpbin.org/get",
        params={"limit": 10},
    )

    response.raise_for_status()
    print(response.status_code)
    print(response.headers["content-type"])
    print(response.json())
```

:::

## Streaming Response

Use `Client.stream()` or `AsyncClient.stream()` when the final response body
should be read incrementally. The stream is a context-managed response; leaving
the context before EOF aborts the body and releases the active request slot.

```python
import foghttp
from foghttp.methods import GET


with foghttp.Client() as client:
    with client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response:
        response.raise_for_status()

        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)

        print(response.status_code, total)
```

```python
import asyncio

import foghttp
from foghttp.methods import GET


async def main() -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response:
            response.raise_for_status()

            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)

            print(response.status_code, total)


asyncio.run(main())
```

Streaming responses can be consumed once as bytes, text, or lines:

```python
with foghttp.Client() as client:
    with client.stream(GET, "https://httpbin.org/stream/3") as response:
        response.raise_for_status()

        for line in response.iter_lines(max_line_chars=256 * 1024):
            print(line)
```

See [Response streaming](./streaming.md) for lifecycle, timeout, redirect,
encoding, and current boundary details.

## Base URL

Use `base_url=` when one client talks to one upstream service. Request URLs can
then be relative paths.

::: code-group

```python [Async]
async with foghttp.AsyncClient(base_url="https://api.example.com/v1") as client:
    response = await client.get("users", params={"limit": 10})
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client(base_url="https://api.example.com/v1") as client:
    response = client.get("users", params={"limit": 10})
    response.raise_for_status()
```

:::

FogHTTP stores `base_url` as a path prefix, so both
`https://api.example.com/v1` and `https://api.example.com/v1/` resolve
`"users"` to `https://api.example.com/v1/users`. A request path that starts
with `/` is root-relative and resolves against the origin root:
`"/users"` becomes `https://api.example.com/users`.

Absolute request URLs ignore `base_url`.

`base_url` must not include query parameters or a fragment. Use client-level or
per-request `params=` for query parameters.

## Default Headers

Use client-level `headers=` for values that should be sent with every request
from that client.

::: code-group

```python [Async]
async with foghttp.AsyncClient(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json", "x-client": "foghttp"},
) as client:
    response = await client.get("users")
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json", "x-client": "foghttp"},
) as client:
    response = client.get("users")
    response.raise_for_status()
```

:::

Per-request headers override client defaults case-insensitively. Repeated
headers are preserved when they are not overridden.

```python
with foghttp.Client(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json"},
) as client:
    response = client.get("users", headers={"accept": "text/plain"})
```

FogHTTP applies the same transport-managed header policy to client defaults and
per-request headers.

## Default Query Parameters

Use client-level `params=` for values that should be appended to every request
from that client, such as API version, locale, tenant, or feature flags.

::: code-group

```python [Async]
async with foghttp.AsyncClient(
    base_url="https://api.example.com/v1",
    params={"api-version": "1", "locale": "en-US"},
) as client:
    response = await client.get("users", params={"limit": 10})
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client(
    base_url="https://api.example.com/v1",
    params={"api-version": "1", "locale": "en-US"},
) as client:
    response = client.get("users", params={"limit": 10})
    response.raise_for_status()
```

:::

Client defaults are appended after query parameters already present in the
request URL and before per-request `params=`. Per-request params do not replace
client defaults; repeated keys are preserved in order.

Client-level params apply to every request built by that client, including
absolute request URLs. If defaults contain credentials or tenant identifiers,
prefer a dedicated client scoped to one upstream.

## Query Parameters

Use `params=` with mappings, repeated pairs, or an already encoded query string.
Existing query parameters in the URL are preserved and new values are appended.

```python
with foghttp.Client() as client:
    response = client.get(
        "https://api.example.com/search?debug=1",
        params=[
            ("tag", "rust"),
            ("tag", "python"),
            ("q", "fog http"),
        ],
    )
```

Mapping values can also be sequences:

```python
params = {
    "tag": ["rust", "python"],
    "page": 2,
}
```

Raw query strings are appended as already encoded data:

```python
params = "tag=rust&tag=python"
```

## Client Lifecycle

Prefer context managers for both sync and async clients. Leaving the context
calls `close()` or `aclose()` and explicitly releases Rust transport resources.

```python
client = foghttp.Client()
try:
    response = client.get("https://httpbin.org/get")
finally:
    client.close()
```

```python
client = foghttp.AsyncClient()
try:
    response = await client.get("https://httpbin.org/get")
finally:
    await client.aclose()
```

The Rust transport is created lazily on the first request, not when the Python
client object is constructed. Calling `close()` or `aclose()` more than once is
safe. After closing a client, new requests and stats calls raise
`ClientClosedError`.

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

See [Client lifecycle](./lifecycle.md) for the full shutdown, cancellation,
lazy initialization, thread/task sharing contract, and opt-in async lifecycle
debug mode.

## JSON Body

Pass `json=` to send a JSON request body. FogHTTP serializes it with `orjson`
and sets `content-type: application/json` automatically.

::: code-group

```python [Async]
async with foghttp.AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
```

:::

## Form Data

Pass `data=` with a mapping or repeated pairs to send a buffered
`application/x-www-form-urlencoded` request body.

::: code-group

```python [Async]
async with foghttp.AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        data={
            "grant_type": "client_credentials",
            "scope": ["read", "write"],
        },
    )
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        data={
            "grant_type": "client_credentials",
            "scope": ["read", "write"],
        },
    )
    response.raise_for_status()
```

:::

If `data=` is `bytes` or `str`, FogHTTP treats it as already encoded buffered
body content and does not add `content-type` automatically.

## Raw Content

Use `content=` for already encoded bytes, text, binary file-like objects, or
bytes-like iterables.

::: code-group

```python [Async]
async with foghttp.AsyncClient() as client:
    response = await client.post(
        "https://httpbin.org/post",
        content=b"raw bytes",
        headers={"content-type": "application/octet-stream"},
    )
```

```python [Sync]
with foghttp.Client() as client:
    response = client.post(
        "https://httpbin.org/post",
        content=b"raw bytes",
        headers={"content-type": "application/octet-stream"},
    )
```

:::

## Request Body Matrix

FogHTTP currently accepts one body source per request:

| Parameter | Current behavior |
|---|---|
| `json=` | Encodes with `orjson` and adds `content-type: application/json` when no explicit content type is set |
| `data=` | Encodes mappings and repeated pairs as `application/x-www-form-urlencoded`; raw `bytes` and `str` are sent as buffered body content |
| `content=` | Accepts buffered `bytes` or `str`, binary file-like objects, sync bytes-like iterables, zero-arg byte-stream factories, and async bytes-like iterables/factories on `AsyncClient`; strings are encoded as UTF-8 and no semantic content type is added |
| `files=` | Builds multipart uploads from bytes-like parts, binary file-like objects, byte streams, or byte-stream factories; can be combined with mapping or repeated-pair `data=` form fields |

Passing incompatible body sources raises `ValueError`; `files=` may be combined
with form-field `data=` mappings or repeated pairs. `Content-Length` and
`Transfer-Encoding` are transport-managed framing headers and are not accepted
in request headers; the Rust transport owns them. Buffered `json=`, `data=`,
byte/string `content=`, and bytes-like multipart file parts are replayable for
the current redirect policy. File-like and direct streaming `content=` or
`files=` bodies are non-replayable, so method-preserving redirects fail closed
instead of replaying a consumed provider. Factory-backed streaming bodies are
replayable because the factory returns a fresh stream per send attempt. Public
provider and multipart type aliases are documented in
[Upload typing contracts](./upload-types.md).

`get()` and `head()` are bodyless convenience helpers. Use `post()`, `put()`,
`patch()`, `delete()`, `request()`, or `stream()` for body parameters. If you
intentionally need a non-standard GET or HEAD body, use the explicit
`request("GET", ..., content=...)` / `request("HEAD", ..., content=...)` form.

## Buffered Response Decoding

Buffered responses with `content-encoding: gzip`, `deflate`, or `br` are
decoded before `response.content`, `response.text`, or `response.json()` see the
body. After successful decoding, FogHTTP removes `content-encoding` and
`content-length` from `response.headers` because they described the encoded wire
body, not the decoded buffered body.

```python
import foghttp


with foghttp.Client(headers={"accept-encoding": "gzip, deflate, br"}) as client:
    response = client.get("https://api.example.com/data")
    print(response.content)
```

FogHTTP does not add `Accept-Encoding` automatically yet. Send that header when
you want to negotiate compressed responses. Unsupported content encodings are
left untouched. Invalid compressed bodies raise `RequestError`. Responses that
must not carry a body, such as `HEAD`, `204 No Content`, `205 Reset Content`,
and `304 Not Modified`, are not decoded and keep their original body metadata
headers.

`response.text` uses the `Content-Type` charset when it names a valid Python
codec. If the charset is missing or invalid, FogHTTP falls back to a Unicode BOM
when present, otherwise to UTF-8.

## Request Metadata

Every response includes lightweight request metadata. The request body is not
stored.

```python
print(response.request.method)
print(response.request.url)
print(response.request.headers)
```

For redirects, `response.request` describes the final request, and each item in
`response.history` keeps request metadata for that redirect hop.

`raise_for_status()` uses this metadata in `HTTPStatusError` messages:

```text
GET https://api.example.com/users/123 returned 404 Not Found
```

Use response status flags when application code needs branch-friendly status
checks without raising:

```python
if response.is_success:
    print(response.json())
elif response.is_redirect:
    print(response.headers.get("location"))
elif response.is_error:
    response.raise_for_status()
```

## Prepared Requests

Build a `foghttp.Request` separately when application code needs to inspect or
adjust the request before sending it.

::: code-group

```python [Async]
import foghttp
from foghttp.methods import POST


async with foghttp.AsyncClient() as client:
    request = client.build_request(
        POST,
        "https://httpbin.org/post",
        json={"name": "Ada Lovelace"},
    )
    response = await client.send(request)
    response.raise_for_status()
```

```python [Sync]
import foghttp
from foghttp.methods import POST


with foghttp.Client() as client:
    request = client.build_request(
        POST,
        "https://httpbin.org/post",
        json={"name": "Ada Lovelace"},
    )
    response = client.send(request)
    response.raise_for_status()
```

:::

## Headers

`response.headers` and `response.request.headers` are `foghttp.Headers`
objects. Header lookup is case-insensitive, and repeated values are preserved.
Response header bytes, including HTTP obs-text values, are exposed as Latin-1
strings so non-UTF-8 header values are preserved instead of silently dropped.

```python
cookies = response.headers.get_list("set-cookie")

headers = foghttp.Headers(
    [
        ("x-repeat", "one"),
        ("x-repeat", "two"),
    ],
)

with foghttp.Client() as client:
    response = client.get("https://httpbin.org/headers", headers=headers)
```

FogHTTP treats authority, framing, and hop-by-hop request headers as
transport-managed. The safe API rejects manual `Host`, `Content-Length`,
`Transfer-Encoding`, `TE`, `Trailer`, `Connection`, `Upgrade`, `Keep-Alive`,
`Proxy-Connection`, and `Proxy-Authorization` headers. Use semantic headers
such as `Accept`, `Authorization`, `Content-Type`, and application-specific
`X-*` headers.

Debug-facing representations and `HTTPStatusError` messages redact sensitive
header values, URL credentials, common token query or fragment parameters, and
buffered body bytes. Explicit APIs such as `headers["authorization"]`,
`str(url)`, and `response.content` still return the real values.

For a parameter-by-parameter compatibility map with common Python HTTP clients,
see [Request builder compatibility](./request-builder.md).

## Custom CA Certificates

FogHTTP uses WebPKI roots by default for HTTPS. For private services with an
internal certificate authority, pass explicit CA certificate files through
`TLSConfig`. Custom CA files are added to WebPKI roots by default.

```python
from pathlib import Path

import foghttp


tls = foghttp.TLSConfig(
    ca_certificates=(Path("/etc/company/ca.pem"),),
)

with foghttp.Client(tls=tls) as client:
    response = client.get("https://internal-api.example.com/health")
    response.raise_for_status()
```

The same `TLSConfig` works with `AsyncClient`. Disabling certificate
verification is intentionally not exposed; use a trusted CA bundle instead.
For custom-only enterprise trust, pass `trust_webpki_roots=False` together with
one or more CA certificate files.

```python
tls = foghttp.TLSConfig(
    ca_certificates=("/etc/company/ca.pem",),
    trust_webpki_roots=False,
)
```

See [TLS trust](./tls.md) for the full trust-boundary contract.

## URL

Use `foghttp.URL` when application code needs normalized URL parts or origin
comparison.

```python
url = foghttp.URL("https://Example.COM:443/users")

print(str(url))
print(url.origin)
print(url.is_same_origin("https://example.com/profile"))
```

## Transport Limits and Stats

```python
import foghttp


limits = foghttp.Limits(
    max_active_requests=100,
    max_active_requests_per_origin=20,
    max_connections_per_host=20,
    max_pending_requests=1000,
    max_response_body_size=10 * 1024 * 1024,
    max_buffered_response_bytes=100 * 1024 * 1024,
    idle_timeout=30.0,
)

timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=1.0,
    read=10.0,
    total=30.0,
)

async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
    response = await client.get("https://httpbin.org/get")
    print(client.stats())
```

`Timeouts.pool` controls waiting for Rust-side acquire gates and raises
`PoolTimeout` when the acquire queue is full or a request waits too long for a
slot. `Timeouts.total` is the broader buffered transport deadline and raises the
base `TimeoutError` when it expires. `Timeouts.read` controls how long FogHTTP
waits for the next response body frame/chunk while collecting a buffered
response and raises `ReadTimeout` when body progress stalls.
Timeout exceptions include a safe `diagnostic` object when FogHTTP can identify
the phase, elapsed time, configured budget, normalized origin, and redirect hop.

`Limits.max_active_requests` caps active buffered requests for the whole client.
`Limits.max_active_requests_per_origin` defaults to `None`; set it to cap active
buffered requests for one normalized origin. `Limits.max_pending_requests` caps
requests waiting in the Rust-side FIFO acquire queue. `Limits.max_response_body_size`
defaults to `10 * 1024 * 1024` bytes and protects one response.
`Limits.max_connections` defaults to `None`; set it to add an explicit global
cap on tracked physical connections for the whole client. `Limits.max_connections_per_host`
defaults to `None`; set it to cap tracked physical connections for one
normalized origin. Connection-limit waits use `Timeouts.pool`, report
`PoolTimeout.diagnostic.phase == "connection_acquire"`, and are reported
through separate `connection_acquire_*` transport stats. Idle keep-alive
connections count against explicit connection caps until they are reused,
closed, or removed by transport pool cleanup.
`Limits.max_buffered_response_bytes` defaults to `100 * 1024 * 1024` bytes and
protects aggregate in-flight buffered response bodies across concurrent
requests. Set smaller or larger explicit limits for your workload, or pass
`None` only when unbounded buffering is an intentional opt-in.
For compressed responses, `Limits.max_response_body_size` applies to both the
encoded wire body and the decoded buffered body. The aggregate buffered budget
also covers bytes held while decoding, so compressed responses remain bounded
under concurrency.
`Limits.max_idle_connections_per_host` controls idle keep-alive pool capacity;
it is not an active connection cap and is separate from request-slot and
connection-slot backpressure.

`TransportStats.buffered_response_bytes` reports currently reserved in-flight
buffered body bytes. `TransportStats.buffered_response_budget_rejections`
reports requests rejected by the aggregate buffered memory budget.
`TransportStats.response_body_reuse_eligible`, `response_body_closed`, and
`response_body_aborted` report Rust-side buffered body lifecycle outcomes:
clean reusable-eligible completion, clean non-reusable completion, and aborted
body handling.
`TransportStats.connections_opened`, `connections_open_failed`,
`connections_closed`, `connections_reused`, `connections_aborted`,
`active_connections`, and `idle_connections` report Rust-side socket lifecycle
telemetry observed around the connector and buffered response lifecycle.
`TransportStats.connection_acquire_attempts`, `connection_acquire_waited`, and
`connection_acquire_timeouts` report pressure from physical connection caps.
`client.dump_transport_state()["origins"]` shows request-slot pressure,
connection-limit pressure, and socket lifecycle fields grouped by normalized
origin without path, query, userinfo, headers, or body data.
Default ports are omitted from origin keys; non-default ports are preserved.
Each origin also exposes `last_activity_at_ns`, a monotonic timestamp relative
to the current transport metrics lifetime, not a Unix epoch timestamp.
Use `client.dump_pool_diagnostics()` when a workload appears stuck waiting for
capacity: it reports current active holders, pending waiters, the oldest pending
wait age, whether another pending waiter can be admitted, and whether requests
are waiting on the global active request limit, per-origin active request limit,
or both.
`TransportStats` and the `dump_*` APIs include `schema_version` plus a
monotonic `snapshot_sequence` within one Rust transport lifetime. Use
`TransportStats` for dashboards and alert-oriented metrics; see
[Telemetry contract](./telemetry.md) for the current guarantees.

For opt-in event hooks, pass a typed telemetry config. Hooks receive redacted
`TelemetryEvent` objects and are intended for logging/tracing bridges, not for
mutating requests or responses. Hooks run inline, so keep sinks fast and
non-blocking. The default hook error policy is development-strict; production
exporters usually should use `on_hook_error="warn"` or `"ignore"`:

```python
class Sink:
    def emit(self, event: foghttp.TelemetryEvent) -> None:
        print(event.event_type, event.redacted_url, event.outcome)


with foghttp.Client(telemetry=foghttp.TelemetryConfig(sink=Sink())) as client:
    response = client.get("https://httpbin.org/get?token=secret")
```

`Timeouts.connect` is client-level connector configuration. Per-request
`timeout=` currently affects `pool`, `read`, `write`, and `total`, not
`connect`. See [Timeout model](./timeouts.md) for the detailed current contract
and limitations.

## Runtime Workers

FogHTTP uses a shared Tokio runtime by default. Client construction and
closing a never-used client do not create Rust transport or runtime resources.
The shared runtime is initialized lazily when the first shared-runtime client
actually opens transport state.

Most applications should keep the default shared runtime and reuse long-lived
clients. For isolation or benchmarking, pass `runtime="dedicated"` to give a
client its own Tokio runtime:

```python
with foghttp.Client(runtime="dedicated") as client:
    response = client.get("https://httpbin.org/get")
```

For advanced dedicated-runtime tuning, pass `runtime_workers=` explicitly:

```python
with foghttp.Client(runtime="dedicated", runtime_workers=4) as client:
    response = client.get("https://httpbin.org/get")
```

`runtime_workers` must be between `1` and `32` and requires a dedicated
runtime. If `runtime=` is omitted and `runtime_workers` or the
`FOGHTTP_RUNTIME_WORKERS` environment variable is set, FogHTTP uses a dedicated
runtime to preserve the worker-count contract without making the shared runtime
depend on first-client initialization order.

## Status Codes

Status code constants are grouped by response class.

```python
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import REDIRECT_STATUS_CODES
from foghttp.status_codes.success import OK
```

HTTP method constants are available through `foghttp.methods` for code that
shares method names across prepared requests or helper layers.

```python
from foghttp.methods import GET, POST
```
