<p align="center">
  <img src="https://raw.githubusercontent.com/AmberFog/foghttp/main/logo.png" alt="FogHTTP logo" width="260">
</p>

<h1 align="center">FogHTTP</h1>

<p align="center">
  Rust-powered HTTP client for Python with sync and asyncio APIs.
</p>

FogHTTP is an early MVP HTTP client. The public API is Python-first, while the
transport core is implemented in Rust on top of `hyper`.

FogHTTP is positioned as an observable, high-concurrency Rust-powered transport
for Python services. It is built for controlled service-to-service HTTP
workloads where explicit lifecycle, predictable resource usage, cancellation,
redirect history, and request backpressure visibility matter more than
browser-like feature parity.

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Why FogHTTP

- Rust `hyper` transport with a Python-first API
- sync and asyncio clients with the same request model
- explicit `close()`/`aclose()` lifecycle for Rust transport resources
- graceful sync `close()` for in-flight requests and cancellable async requests
- bounded global/per-origin request backpressure, FIFO pending-acquire limits,
  explicit HTTP/1.1 connection caps, and per-origin pressure diagnostics
- typed telemetry event hooks with redacted request/response lifecycle events
- versioned telemetry snapshots that separate alert-oriented stats from
  diagnostic dump APIs
- opt-in Rust-owned retries with replayability gates and immutable attempt
  traces, plus opt-in per-hop and post-DNS SSRF destination controls
- opt-in async lifecycle debug snapshots for staging and tests
- lazy process-wide shared Tokio runtime by default, opt-in dedicated runtime
  tuning, and fail-closed client ownership across `fork()`
- focused HTTP surface for JSON, form, streaming upload, and multipart API
  workloads in internal services, workers, and benchmarks

## Install

```bash
pip install foghttp
```

Runtime requirements:

- Python `>=3.11`
- `orjson>=3.11,<4`

Published CPython wheels use the stable `cp311-abi3` ABI: each supported
OS/architecture pair has one wheel for the currently validated GIL-enabled
CPython 3.11 through 3.14 range. Newer Python versions are not part of the
compatibility claim until they pass the same release checks. See [Packaging and Python compatibility](https://github.com/AmberFog/foghttp/blob/main/docs/packaging.md)
for the complete wheel matrix and validation policy.

## Quick Start

```python
import foghttp


with foghttp.Client(
    base_url="https://api.example.com",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
) as client:
    response = client.get(
        "users",
        params={"limit": 10},
    )

    response.raise_for_status()
    print(response.status_code)
    print(response.json())
```

Async clients use the same request API:

```python
import foghttp


async with foghttp.AsyncClient() as client:
    response = await client.post(
        "https://api.example.com/users",
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
```

## What Works Today

- sync `Client` and async `AsyncClient`
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and RFC 10008 `QUERY`
- `base_url` for reusable API clients and relative request paths
- default client headers and query params for reusable API clients
- query params with repeated keys, JSON, form-urlencoded data, buffered
  bytes/text bodies, binary file-like request bodies, and streaming
  bytes-like upload providers
- multipart `files=` uploads with bytes-like parts, binary file-like objects,
  direct byte streams, and replayable byte-stream factories
- buffered `Response` with status flags, charset-aware `text`, `json()`,
  `raise_for_status()`, and request metadata
- transparent `gzip`, `deflate`, and `br` decoding for buffered responses
- sync and async bytes/text/line response streaming with explicit
  context-managed lifecycle
- prepared `Request` objects with `build_request()` and `send()`
- immutable request `extensions` for policy/application metadata outside the HTTP message
- case-insensitive `Headers` with repeated values
- safe policy for transport-managed request headers
- redacted repr/error surfaces for sensitive headers, URL credentials,
  token-like URL params, and buffered body bytes
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST/QUERY redirects with final URL, history, typed same-origin and
  cross-origin header policy, and no cross-origin body replay
- HTTP proxy routing and HTTPS proxy `CONNECT` tunnelling through explicit
  `proxy=` or `trust_env=True` when the proxy endpoint uses `http://`
- HTTPS with default WebPKI roots, explicit custom CA certificates, and
  custom-only CA trust
- graceful sync `close()` that waits for in-flight sync requests
- async request cancellation that aborts the in-flight Rust request
- bounded global and per-origin request slots with a bounded FIFO pending queue
- opt-in global/per-origin HTTP/1.1 connection caps with separate connection
  acquire pressure and idle lifecycle diagnostics
- opt-in typed telemetry event hooks for request, redirect, response headers,
  response body, and request completion lifecycle
- opt-in typed transport policy hooks for lightweight request admission and
  response-head checks without default-path Python callbacks
- opt-in Rust-owned retry policy for selected statuses and pre-header network
  failures, with safe methods, replayable bodies, and immutable attempt traces
- opt-in Rust-owned SSRF destination policy with per-hop allowlists,
  post-resolution IP checks, and DNS rebinding mitigation
- versioned telemetry snapshot metadata for `stats()`, `dump_transport_state()`,
  and `dump_pool_diagnostics()`
- opt-in async lifecycle debug mode for active request snapshots, strict leak
  checks, and unclosed-client diagnostics
- default per-response and aggregate buffered response body limits for memory
  safety
- shared Tokio runtime by default, with opt-in dedicated runtime worker tuning
- grouped HTTP status constants and reusable HTTP method constants
- client-level Basic and synchronous callable authentication with retry refresh
  and cross-origin credential stripping

## Documentation

- [Documentation](https://github.com/AmberFog/foghttp/blob/main/docs/index.md)
- [Quickstart](https://github.com/AmberFog/foghttp/blob/main/docs/quickstart.md)
- [Request builder compatibility](https://github.com/AmberFog/foghttp/blob/main/docs/request-builder.md)
- [Authentication](https://github.com/AmberFog/foghttp/blob/main/docs/auth.md)
- [Client lifecycle](https://github.com/AmberFog/foghttp/blob/main/docs/lifecycle.md)
- [Packaging and Python compatibility](https://github.com/AmberFog/foghttp/blob/main/docs/packaging.md)
- [Timeout model](https://github.com/AmberFog/foghttp/blob/main/docs/timeouts.md)
- [Upload typing contracts](https://github.com/AmberFog/foghttp/blob/main/docs/upload-types.md)
- [Transport policy hooks](https://github.com/AmberFog/foghttp/blob/main/docs/policy-hooks.md)
- [Retry policy](https://github.com/AmberFog/foghttp/blob/main/docs/retries.md)
- [SSRF protection](https://github.com/AmberFog/foghttp/blob/main/docs/ssrf.md)
- [Telemetry contract](https://github.com/AmberFog/foghttp/blob/main/docs/telemetry.md)
- [Response streaming](https://github.com/AmberFog/foghttp/blob/main/docs/streaming.md)
- [Proxy and trust_env](https://github.com/AmberFog/foghttp/blob/main/docs/proxies.md)
- [TLS trust](https://github.com/AmberFog/foghttp/blob/main/docs/tls.md)
- [Use cases](https://github.com/AmberFog/foghttp/blob/main/docs/use-cases.md)
- [Redirects](https://github.com/AmberFog/foghttp/blob/main/docs/redirects.md)
- [Limitations](https://github.com/AmberFog/foghttp/blob/main/docs/limitations.md)
- [Benchmarks](https://github.com/AmberFog/foghttp/blob/main/docs/benchmarks.md)
- [Runnable examples](https://github.com/AmberFog/foghttp/tree/main/examples)

## Current Limitations

FogHTTP is currently focused on controlled HTTP workloads. Buffered responses
are the broadest supported response path; sync and async response streaming are
available as bytes/text/line context-managed APIs. Streaming `content=` uploads
and multipart `files=` uploads are available with explicit replayability and
cleanup rules. HTTP proxy routing and HTTPS proxy `CONNECT` tunnelling are
available through `proxy=` and `trust_env=True` when the proxy endpoint itself
uses `http://`. Proxy-routed requests fail closed when `SSRFPolicy` is enabled
because the client cannot prove which target address a remote proxy resolves.
Cookies, provider-specific OAuth flows, HTTP/2, automatic `Accept-Encoding`
negotiation, streaming decompression, and per-request connect timeout
reconfiguration are planned for later versions. Physical connection caps
currently apply to the HTTP/1.1 connector path; HTTP/2 will require separate
stream-level limits.
Response body read timeout is available for buffered and streaming response
bodies; request body write timeout is available for buffered and streaming
request bodies. Socket lifecycle telemetry is available for the current HTTP/1
path. Disabling TLS verification is intentionally not supported.

## Development

Development requires a Rust toolchain with `cargo` available in `PATH`.

```bash
uv run --extra dev --with "maturin>=1.7,<2" maturin develop --locked --skip-install
uv run --extra dev coverage run -m pytest
uv run --extra dev coverage report -m
uv run --extra dev pre-commit run --all-files --show-diff-on-failure
```
