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
- explicit `close()`/`aclose()` lifecycle for Rust runtime resources
- graceful sync `close()` for in-flight requests and cancellable async requests
- global/per-origin request backpressure, per-origin acquire pressure stats, and
  stuck request diagnostics
- advanced per-client Tokio runtime worker tuning
- focused buffered HTTP surface for JSON and form APIs, internal services,
  workers, and benchmarks

## Install

```bash
pip install foghttp
```

Runtime requirements:

- Python `>=3.11`
- `orjson>=3.11,<4`

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
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`
- `base_url` for reusable API clients and relative request paths
- default client headers and query params for reusable API clients
- query params with repeated keys, JSON, form-urlencoded data, and buffered
  bytes/text bodies
- buffered `Response` with status flags, charset-aware `text`, `json()`,
  `raise_for_status()`, and request metadata
- transparent `gzip`, `deflate`, and `br` decoding for buffered responses
- sync and async bytes/text/line response streaming with explicit
  context-managed lifecycle
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated values
- safe policy for transport-managed request headers
- redacted repr/error surfaces for sensitive headers, URL credentials,
  token-like URL params, and buffered body bytes
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST redirects with final URL, history, and conservative replay policy
- HTTPS with default WebPKI roots, explicit custom CA certificates, and
  custom-only CA trust
- graceful sync `close()` that waits for in-flight sync requests
- async request cancellation that aborts the in-flight Rust request
- global and per-origin request backpressure, per-origin acquire pressure
  snapshots, stuck request diagnostics, and HTTP/1.1 over HTTP/HTTPS
- default per-response and aggregate buffered response body limits for memory
  safety
- advanced per-client Tokio runtime worker tuning
- grouped HTTP status constants and reusable HTTP method constants

## Documentation

- [Documentation](https://github.com/AmberFog/foghttp/blob/main/docs/index.md)
- [Quickstart](https://github.com/AmberFog/foghttp/blob/main/docs/quickstart.md)
- [Request builder compatibility](https://github.com/AmberFog/foghttp/blob/main/docs/request-builder.md)
- [Client lifecycle](https://github.com/AmberFog/foghttp/blob/main/docs/lifecycle.md)
- [Timeout model](https://github.com/AmberFog/foghttp/blob/main/docs/timeouts.md)
- [Telemetry contract](https://github.com/AmberFog/foghttp/blob/main/docs/telemetry.md)
- [Response streaming](https://github.com/AmberFog/foghttp/blob/main/docs/streaming.md)
- [TLS trust](https://github.com/AmberFog/foghttp/blob/main/docs/tls.md)
- [Use cases](https://github.com/AmberFog/foghttp/blob/main/docs/use-cases.md)
- [Redirects](https://github.com/AmberFog/foghttp/blob/main/docs/redirects.md)
- [Limitations](https://github.com/AmberFog/foghttp/blob/main/docs/limitations.md)
- [Benchmarks](https://github.com/AmberFog/foghttp/blob/main/docs/benchmarks.md)
- [Runnable examples](https://github.com/AmberFog/foghttp/tree/main/examples)

## Current Limitations

FogHTTP is currently focused on controlled HTTP workloads. Buffered responses
are the broadest supported path; sync and async response streaming are available
as bytes/text/line context-managed APIs. Streaming uploads, cookies, auth helpers,
proxy support, multipart uploads, HTTP/2, automatic `Accept-Encoding`
negotiation, streaming decompression, strict connection-level pool limits,
per-request connect timeout reconfiguration, and request-body write timeout
semantics are planned for later versions. Response body read timeout is
available for buffered and streaming response bodies. Socket lifecycle telemetry
is available for the current HTTP/1 path. Disabling TLS verification is
intentionally not supported.

## Development

Development requires a Rust toolchain with `cargo` available in `PATH`.

```bash
uv run --extra dev --with "maturin>=1.7,<2" maturin develop
uv run --extra dev coverage run -m pytest
uv run --extra dev coverage report -m
uv run --extra dev pre-commit run --all-files --show-diff-on-failure
```
