<p align="center">
  <img src="logo.png" alt="FogHTTP logo" width="160">
</p>

<h1 align="center">FogHTTP</h1>

<p align="center">
  Rust-powered async HTTP client for Python, optimized for high concurrency,
  explicit resource management, and observable connection pooling.
</p>

FogHTTP is currently an MVP. The public API is Python-first and `asyncio`
native; the HTTP core is implemented in Rust on top of `hyper`.

## Install for development

```bash
uv run maturin develop
```

## Usage

```python
import foghttp


async with foghttp.AsyncClient(
    limits=foghttp.Limits(
        max_connections=100,
        max_connections_per_host=20,
        max_pending_acquires=1000,
        idle_timeout=30.0,
    ),
    timeouts=foghttp.Timeouts(
        connect=2.0,
        read=10.0,
        write=10.0,
        pool=1.0,
        total=30.0,
    ),
) as client:
    response = await client.get(
        "https://api.example.com/users",
        headers={"accept": "application/json"},
        params={"limit": 10},
    )

    response.raise_for_status()
    data = response.json()
    print(client.stats())
```

## MVP Scope

- `AsyncClient`
- `request`, `get`, `post`, `put`, `patch`, `delete`
- buffered `Response`
- `Limits`
- `Timeouts`
- global acquire backpressure via `max_connections`
- `stats()`
- HTTP/1.1 over HTTP and HTTPS

Streaming, redirects, cookies, proxies, multipart bodies, and richer pool
introspection are intentionally left for later versions.
