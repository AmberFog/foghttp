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
- cancellable async requests that abort in-flight Rust work
- global/per-origin request backpressure and observable request stats
- focused buffered HTTP surface for JSON APIs, internal services, workers, and
  benchmarks

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


with foghttp.Client() as client:
    response = client.get(
        "https://api.example.com/users",
        headers={"accept": "application/json"},
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
- query params, JSON bodies, and buffered bytes/text bodies
- buffered `Response` with `text`, `json()`, `raise_for_status()`, and request
  metadata
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated values
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST redirects with final URL and history
- async request cancellation that aborts the in-flight Rust request
- global and per-origin request backpressure, basic stats, and HTTP/1.1 over
  HTTP/HTTPS
- optional buffered response body size limit for memory safety
- grouped HTTP status constants

## Documentation

- [Documentation](https://github.com/AmberFog/foghttp/blob/main/docs/index.md)
- [Quickstart](https://github.com/AmberFog/foghttp/blob/main/docs/quickstart.md)
- [Use cases](https://github.com/AmberFog/foghttp/blob/main/docs/use-cases.md)
- [Redirects](https://github.com/AmberFog/foghttp/blob/main/docs/redirects.md)
- [Limitations](https://github.com/AmberFog/foghttp/blob/main/docs/limitations.md)
- [Benchmarks](https://github.com/AmberFog/foghttp/blob/main/docs/benchmarks.md)
- [Runnable examples](https://github.com/AmberFog/foghttp/tree/main/examples)

## Current Limitations

FogHTTP is currently focused on controlled buffered HTTP workloads. Streaming
bodies, cookies, auth helpers, proxy support, multipart uploads, HTTP/2,
compression decoding, true connection-level pool metrics, per-request connect
timeout reconfiguration, and separate read/write timeout semantics are planned
for later versions.

## Development

```bash
uv run --with "maturin>=1.7,<2" maturin develop
uv run --extra dev coverage run -m pytest
uv run --extra dev coverage report -m
pre-commit run --all-files
```
