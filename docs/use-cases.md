# Use Cases

FogHTTP is useful today when the workload is simple, explicit, and controlled.
Think service-to-service calls, bounded buffered bodies, and context-managed
response streaming rather than browser-like sessions. Its strongest current fit
is Python service code that wants a small API, Rust-backed transport execution,
predictable cancellation, redirect/debug metadata, and observable request
backpressure without adopting a large client surface.

## Works Well Today

### Internal JSON API Clients

FogHTTP is a good fit for API clients that send JSON, receive JSON, and keep
request bodies reasonably small.

::: code-group

```python [Async]
import foghttp


async def load_user(user_id: str) -> dict:
    async with foghttp.AsyncClient() as client:
        response = await client.get(
            f"https://api.example.com/users/{user_id}",
            headers={"accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
```

```python [Sync]
import foghttp


def load_user(user_id: str) -> dict:
    with foghttp.Client() as client:
        response = client.get(
            f"https://api.example.com/users/{user_id}",
            headers={"accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()
```

:::

### Async Fan-Out

`AsyncClient` is useful when you need many concurrent buffered requests with
global and per-origin active request limits, acquire backpressure, and
cancellation that aborts the in-flight Rust request.

```python
import asyncio

import foghttp


async def fetch_many(urls: list[str]) -> list[dict]:
    limits = foghttp.Limits(
        max_active_requests=100,
        max_active_requests_per_origin=20,
        max_pending_requests=1000,
        max_buffered_response_bytes=100 * 1024 * 1024,
    )

    async with foghttp.AsyncClient(limits=limits) as client:
        responses = await asyncio.gather(*(client.get(url) for url in urls))

    return [response.json() for response in responses]
```

See [async_resource_limits.py](../examples/async_resource_limits.py) for a
runnable example with explicit global and per-origin request limits.

### Cancellable Async Requests

For bounded async work, use normal `asyncio` cancellation primitives. If the
task is cancelled while the Rust transport request is in flight, FogHTTP aborts
that request and clears the observed active request state.

```python
import asyncio

import foghttp


async def load_with_budget(url: str) -> bytes:
    async with foghttp.AsyncClient() as client:
        async with asyncio.timeout(1.0):
            response = await client.get(url)
            response.raise_for_status()
            return response.content
```

### CLI Scripts and Background Workers

The sync client is useful for scripts, one-off maintenance jobs, and workers
that do not need an event loop.

```python
import foghttp


def send_event(payload: dict) -> None:
    with foghttp.Client() as client:
        response = client.post(
            "https://events.example.com/ingest",
            json=payload,
        )
        response.raise_for_status()
```

### Streaming Downloads

Use `stream()` when a response should be consumed incrementally instead of
collected into `Response.content`.

::: code-group

```python [Async]
async with foghttp.AsyncClient() as client:
    async with client.stream("GET", "https://api.example.com/export") as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            process(chunk)
```

```python [Sync]
with foghttp.Client() as client:
    with client.stream("GET", "https://api.example.com/export") as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            process(chunk)
```

:::

Bytes are the source of truth. Text and line iterators are available as
incremental helpers over the same stream:

```python
with foghttp.Client() as client:
    with client.stream("GET", "https://api.example.com/events") as response:
        response.raise_for_status()
        for line in response.iter_lines():
            process_event(line)
```

Streaming decompression and streaming uploads are planned separately.

### Redirect-Aware APIs

FogHTTP can follow GET, HEAD, and POST redirects, preserve redirect history, and
apply conservative cross-origin header stripping and body replay protection.

```python
import foghttp


with foghttp.Client(follow_redirects=True) as client:
    response = client.post(
        "https://api.example.com/old-submit",
        json={"name": "Ada"},
    )

print(response.url)
print([item.status_code for item in response.history])
print(response.request.method)
```

### Debugging Client Behavior

The response contains final URL, request metadata, elapsed time, HTTP version,
headers, and redirect history.

```python
print(response.status_code)
print(response.url)
print(response.request.method, response.request.url)
print(response.elapsed)
print(response.http_version)
print(response.history)
```

### Inspecting Prepared Requests

Use `build_request()` when application code needs to inspect or adjust headers,
URL, or body bytes before sending a buffered request.

```python
import foghttp
from foghttp.methods import POST


with foghttp.Client() as client:
    request = client.build_request(
        POST,
        "https://api.example.com/users",
        json={"name": "Ada"},
    )
    request.headers["x-trace"] = "manual"
    response = client.send(request)
```

### One-Upstream API Clients

Use `base_url` for service clients that send many requests to the same
upstream. Relative paths keep call sites focused on API resources instead of
repeating the origin every time.

```python
with foghttp.Client(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
) as client:
    response = client.get("users", params={"limit": 10})
    response.raise_for_status()
```

## Usable With Constraints

### Manual Bearer Tokens

FogHTTP does not yet have an `auth=` API, but simple static tokens work through
headers.

```python
headers = {"authorization": f"Bearer {token}"}
response = client.get("https://api.example.com/me", headers=headers)
```

For one-upstream clients with a static token, client-level `headers=` can avoid
repeating the same header at every call site.

For token refresh, retries after `401`, request signing, or OAuth flows, wait
for the planned auth/hooks layer or keep that logic outside FogHTTP.

### Small Buffered Uploads

`json=` works for JSON, `data=` works for small form-urlencoded bodies, and
`content=` works for buffered bytes and strings. Pass only one body source per
request. Large file uploads, streaming bodies, and `files=` should wait for the
planned body support.

```python
response = client.post(
    "https://api.example.com/import",
    content=b"small payload",
    headers={"content-type": "application/octet-stream"},
)
```

```python
response = client.post(
    "https://api.example.com/oauth/token",
    data={"grant_type": "client_credentials", "scope": ["read", "write"]},
)
```

### Simple Error Handling

`raise_for_status()` raises `HTTPStatusError` for `4xx` and `5xx`. Error
messages include the request method, URL, status code, and reason phrase.

```python
try:
    response.raise_for_status()
except foghttp.HTTPStatusError as exc:
    print(exc)
    print(exc.response.status_code)
    print(exc.response.url)
```

## Not A Good Fit Yet

| Need | Status |
|---|---|
| Streaming text/line helpers | Available for sync and async response streams |
| Streaming decompression | Not implemented; buffered responses support transparent decoding |
| Streaming uploads | Not implemented |
| Multipart files | Not implemented |
| Cookies/session jar | Not implemented |
| Proxy and `trust_env` | Not implemented |
| HTTP/2 | Not implemented |
| Cookie jar and auth helper integration | Not implemented; cross-origin redirects still strip sensitive headers and drop body replay |
| Unbounded buffered large downloads | `max_response_body_size` defaults to 10 MiB and `max_buffered_response_bytes` defaults to 100 MiB for buffered fail-fast protection; use `stream()` for incremental byte downloads |
| Automatic compression negotiation | Not implemented; pass `Accept-Encoding` manually when you want compressed buffered responses |

FogHTTP is best today in controlled environments where request bodies are small
and response bodies either fit in memory or can be consumed through
context-managed bytes/text/line streaming. `gzip`, `deflate`, and `br` response
bodies are decoded for buffered responses, and body limits still apply to the
decoded bytes. Keep `max_response_body_size` and `max_buffered_response_bytes`
finite unless unbounded buffering is a deliberate opt-in for a trusted endpoint.
