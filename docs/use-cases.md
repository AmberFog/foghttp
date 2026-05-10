# Use Cases

FogHTTP is useful today when the workload is simple, explicit, and buffered.
Think controlled service-to-service calls rather than browser-like sessions.
Its strongest current fit is Python service code that wants a small API,
Rust-backed transport execution, predictable cancellation, redirect/debug
metadata, and observable pool pressure without adopting a large client surface.

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
global connection limits, pool backpressure, and cancellation that aborts the
in-flight Rust request.

```python
import asyncio

import foghttp


async def fetch_many(urls: list[str]) -> list[dict]:
    limits = foghttp.Limits(max_connections=100, max_pending_acquires=1000)

    async with foghttp.AsyncClient(limits=limits) as client:
        responses = await asyncio.gather(*(client.get(url) for url in urls))

    return [response.json() for response in responses]
```

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

### Redirect-Aware APIs

FogHTTP can follow GET, HEAD, and POST redirects and preserve redirect history.

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
with foghttp.Client() as client:
    request = client.build_request(
        "POST",
        "https://api.example.com/users",
        json={"name": "Ada"},
    )
    request.headers["x-trace"] = "manual"
    response = client.send(request)
```

## Usable With Constraints

### Manual Bearer Tokens

FogHTTP does not yet have an `auth=` API, but simple static tokens work through
headers.

```python
headers = {"authorization": f"Bearer {token}"}
response = client.get("https://api.example.com/me", headers=headers)
```

For token refresh, retries after `401`, request signing, or OAuth flows, wait
for the planned auth/hooks layer or keep that logic outside FogHTTP.

### Small Buffered Uploads

`content=` works for bytes and strings, and `json=` works for JSON. Large file
uploads should wait for streaming upload support.

```python
response = client.post(
    "https://api.example.com/import",
    content=b"small payload",
    headers={"content-type": "application/octet-stream"},
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
| Streaming downloads | Not implemented |
| Streaming uploads | Not implemented |
| Multipart files | Not implemented |
| Cookies/session jar | Not implemented |
| Proxy and `trust_env` | Not implemented |
| HTTP/2 | Not implemented |
| Browser-like redirect/cookie/auth policy | Not implemented |
| Large buffered responses protection | Not implemented |

FogHTTP is best today in controlled environments where request and response
bodies are expected to fit in memory.
