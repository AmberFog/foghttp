# Getting Started

## Install for Development

```bash
uv run --with "maturin>=1.7,<2" maturin develop
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

## Client Lifecycle

Prefer context managers for both sync and async clients. Leaving the context
calls `close()` or `aclose()` and explicitly releases the Rust client runtime,
connection pool resources, and associated transport state.

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

Calling `close()` or `aclose()` more than once is safe. After closing a client,
new requests and stats calls raise `ClientClosedError`.

For async clients, cancelling a task that is waiting on a request aborts the
in-flight Rust request and releases the observed active request state. Calling
`aclose()` also cancels in-flight async requests before shutting down the Rust
runtime.

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

## Raw Content

Use `content=` for already encoded bytes or text.

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

## Prepared Requests

Build a `foghttp.Request` separately when application code needs to inspect or
adjust the request before sending it.

::: code-group

```python [Async]
async with foghttp.AsyncClient() as client:
    request = client.build_request(
        "POST",
        "https://httpbin.org/post",
        json={"name": "Ada Lovelace"},
    )
    response = await client.send(request)
    response.raise_for_status()
```

```python [Sync]
with foghttp.Client() as client:
    request = client.build_request(
        "POST",
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
    max_pending_requests=1000,
    max_response_body_size=10 * 1024 * 1024,
    idle_timeout=30.0,
)

timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=1.0,
    total=30.0,
)

async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
    response = await client.get("https://httpbin.org/get")
    print(client.stats())
```

`Timeouts.total` governs the whole buffered transport request. `Timeouts.pool`
controls waiting for the Rust-side acquire gates. `Limits.max_active_requests`
caps active buffered requests for the whole client.
`Limits.max_active_requests_per_origin` defaults to `None`; set it to cap active
buffered requests for one normalized origin. `Limits.max_pending_requests` caps
requests waiting for a free acquire permit. `Limits.max_response_body_size`
defaults to `None`; set it to fail safely when a buffered response body grows
beyond the configured byte limit. `Limits.max_idle_connections_per_host` controls
idle keep-alive pool capacity; it is not an active request limit and is separate
from per-origin request backpressure. `Timeouts.connect` is applied by the Rust
transport when establishing connections. Separate `read` and `write` timeout
semantics are reserved for later streaming/body work.

## Runtime Workers

FogHTTP creates a Tokio runtime per client. By default, the runtime worker count
is selected from `Limits.max_active_requests` and capped at `16` workers.

Most applications should keep the default and reuse long-lived clients. For
advanced tuning, pass `runtime_workers=` explicitly:

```python
with foghttp.Client(runtime_workers=4) as client:
    response = client.get("https://httpbin.org/get")
```

`runtime_workers` must be between `1` and `32`. If the argument is not provided,
FogHTTP also accepts the `FOGHTTP_RUNTIME_WORKERS` environment variable for
benchmarking and operational overrides.

## Status Codes

Status code constants are grouped by response class.

```python
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import REDIRECT_STATUS_CODES
from foghttp.status_codes.success import OK
```
