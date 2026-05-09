<p align="center">
  <img src="https://raw.githubusercontent.com/AmberFog/foghttp/main/logo.png" alt="FogHTTP logo" width="260">
</p>

<h1 align="center">FogHTTP</h1>

<p align="center">
  Rust-powered HTTP client for Python with sync and asyncio APIs.
</p>

FogHTTP is an early MVP HTTP client. The public API is Python-first, while the
transport core is implemented in Rust on top of `hyper`.

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

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
- global pool backpressure, basic stats, and HTTP/1.1 over HTTP/HTTPS
- grouped HTTP status constants

## Documentation

- [Documentation](https://github.com/AmberFog/foghttp/blob/main/docs/index.md)
- [Quickstart](https://github.com/AmberFog/foghttp/blob/main/docs/quickstart.md)
- [Use cases](https://github.com/AmberFog/foghttp/blob/main/docs/use-cases.md)
- [Redirects](https://github.com/AmberFog/foghttp/blob/main/docs/redirects.md)
- [Limitations](https://github.com/AmberFog/foghttp/blob/main/docs/limitations.md)
- [Runnable examples](https://github.com/AmberFog/foghttp/tree/main/examples)

## Current Limitations

FogHTTP is currently focused on controlled buffered HTTP workloads. Streaming
bodies, cookies, auth helpers, proxy support, multipart uploads, HTTP/2,
compression decoding, active per-origin connection limits, and separate
read/write timeout semantics are planned for later versions.

## Development

```bash
uv run --with "maturin>=1.7,<2" maturin develop
uv run --extra dev coverage run -m pytest
uv run --extra dev coverage report -m
pre-commit run --all-files
```
