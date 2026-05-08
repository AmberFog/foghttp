<p align="center">
  <img src="logo.png" alt="FogHTTP logo" width="260">
</p>

<h1 align="center">FogHTTP</h1>

<p align="center">
  Rust-powered HTTP client for Python, optimized for high concurrency,
  explicit resource management, and observable connection pooling.
</p>

FogHTTP is currently an MVP. The public API is Python-first and provides both
sync and `asyncio` clients; the HTTP core is implemented in Rust on top of
`hyper`.

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Install for development

```bash
uv run maturin develop
```

Runtime dependencies:

- Python `>=3.11`
- `orjson>=3.11,<4`

Development dependencies include `pytest`, `pytest-asyncio`, and `faker`.

## Usage

### Async

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

### Sync

```python
import foghttp


with foghttp.Client() as client:
    response = client.get(
        "https://api.example.com/users",
        headers={"accept": "application/json"},
        params={"limit": 10},
    )

    response.raise_for_status()
    data = response.json()
```

Each response includes lightweight request metadata without the request body:

```python
print(response.request.method)
print(response.request.url)
print(response.request.headers)
```

### JSON body

```python
import foghttp


with foghttp.Client() as client:
    response = client.post(
        "https://api.example.com/users",
        json={"name": "Ada Lovelace"},
    )

    response.raise_for_status()
```

### Redirects

Redirects are disabled by default. Enable them on the client when you want
FogHTTP to follow GET, HEAD, and POST redirects.

```python
import foghttp
from foghttp.status_codes.redirect import FOUND


with foghttp.Client(follow_redirects=True, max_redirects=20) as client:
    response = client.get("https://example.com/old-location")

    print(response.url)
    print(response.history)

    if response.history and response.history[0].status_code == FOUND:
        print("The request was redirected.")
```

Supported redirect status codes:

- `301 Moved Permanently`
- `302 Found`
- `303 See Other`
- `307 Temporary Redirect`
- `308 Permanent Redirect`

`response.url` contains the final URL. `response.history` contains intermediate
responses in redirect order. If `max_redirects` is exceeded, FogHTTP raises
`RequestError`.

`response.request` describes the final request. Each item in `response.history`
keeps the request metadata for that redirect hop.

POST redirect behavior follows the common browser-compatible rules:

- `301`, `302`, `303`: switch to `GET` and drop the request body
- `307`, `308`: preserve `POST` and resend the request body

### Status codes

HTTP status constants are grouped by response class and can be imported from
the modules that need them:

```python
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import REDIRECT_STATUS_CODES
from foghttp.status_codes.success import OK
```

## MVP Scope

- `Client`
- `AsyncClient`
- `request`, `get`, `head`, `post`, `put`, `patch`, `delete`
- buffered `Response`
- lightweight `Response.request` metadata
- `Limits`
- `Timeouts`
- global acquire backpressure via `max_connections`
- `stats()`
- HTTP/1.1 over HTTP and HTTPS
- GET/HEAD/POST redirects with `follow_redirects=True`, `max_redirects`, final
  URL, redirect history, and POST method/body rules
- grouped HTTP status constants

Streaming, cookies, auth stripping, cross-origin policy, proxy logic, multipart
bodies, and richer pool introspection are intentionally left for later versions.
