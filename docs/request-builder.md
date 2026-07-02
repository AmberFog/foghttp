# Request Builder Compatibility

FogHTTP request building is intentionally small and explicit. The same builder
contract is used by sync clients, async clients, shortcut methods,
`build_request()`, and prepared requests sent with `send()`.

This page maps common `requests`, `httpx`, and `zapros` request parameters to
the current FogHTTP API. The same flow is available as a runnable example in
[request_builder_compatibility.py](../examples/request_builder_compatibility.py).

## Compatibility Matrix

| Common parameter | FogHTTP today | Notes |
|---|---|---|
| `method` | Supported | Methods are normalized to uppercase. Constants are available from `foghttp.methods`. |
| `url` | Supported | Accepts absolute URLs. Relative URLs require client-level `base_url=`. |
| `base_url` | Supported | Client-level only. Query and fragment are rejected; use `params=` instead. |
| `params` | Supported | Accepts mappings, repeated pairs, and raw query strings. Existing URL query is preserved. |
| client default `params` | Supported | Passed as `Client(params=...)` or `AsyncClient(params=...)`. Appended after URL query and before per-request params. |
| `headers` | Supported | Accepts mappings, pairs, and `foghttp.Headers`. Lookups are case-insensitive and repeated values are preserved. |
| client default `headers` | Supported | Passed as `Client(headers=...)` or `AsyncClient(headers=...)`. Per-request headers override defaults case-insensitively. |
| `json` | Supported | Encoded with `orjson`. Adds `content-type: application/json` unless explicitly set. |
| `content` | Supported | Accepts buffered `bytes` or `str`, binary file-like objects, sync bytes-like iterables, zero-arg byte-stream factories, and async bytes-like iterables/factories on `AsyncClient`. Strings are encoded as UTF-8. No semantic content type is added. |
| `data` | Supported | Mappings and repeated pairs are encoded as `application/x-www-form-urlencoded`. Raw `bytes` or `str` are sent as buffered body content without adding a semantic content type. |
| `files` | Supported | Builds `multipart/form-data` uploads. Accepts bytes-like file parts, binary file-like objects, sync byte streams, byte-stream factories, and async byte streams/factories on `AsyncClient`. Can be combined with mapping or repeated-pair `data=` form fields. |
| `auth` | Planned | Use explicit `Authorization` headers for simple static tokens. |
| cookies/session jar | Planned | `cookies=True` is rejected today. |
| proxy / `trust_env` | Supported | HTTP proxy routing and HTTPS `CONNECT` tunnelling through client-level `proxy=` or `trust_env=True` when the proxy endpoint uses `http://`. |
| `timeout` | Partly supported | Per-request `pool`, `read`, `write`, and `total` timeouts are supported. Per-request `connect` does not reconfigure the connector. |
| `follow_redirects` | Supported | Client-level setting. GET/HEAD/POST redirects use conservative security rules. |
| prepared request | Supported | Use `build_request()` and `send()`. Building a request does not create transport state. |

`get()` and `head()` are bodyless convenience helpers: they expose `headers`,
`params`, and `timeout`, but not `json=`, `data=`, `content=`, or `files=`.
If application code intentionally needs an unusual GET or HEAD request body,
use the explicit `request("GET", ..., content=...)` or
`request("HEAD", ..., content=...)` form.

## Merge Order

FogHTTP applies request values in this order:

| Area | Order |
|---|---|
| URL | `base_url` resolution, request URL query, client params, per-request params |
| Headers | client headers, future auth-managed headers, per-request headers |
| Body | one body source: `json=`, `data=`, `content=`, or `files=`; `files=` may include form fields from mapping or repeated-pair `data=` |

Repeated query keys are preserved. Per-request params are appended after client
defaults instead of replacing them, which keeps API-version, tenant, locale, and
feature flag defaults visible in the final URL.

Per-request headers override client defaults case-insensitively. Repeated
headers from defaults are preserved when the request does not override that
header name.

## Sync Example

```python
import foghttp
from foghttp.methods import POST


with foghttp.Client(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
    follow_redirects=True,
) as client:
    response = client.request(
        POST,
        "users?debug=1",
        params=[("role", "admin"), ("role", "operator")],
        headers={"x-trace": "sync-example"},
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
```

The final request URL is equivalent to:

```text
https://api.example.com/v1/users?debug=1&api-version=1&role=admin&role=operator
```

## Async Example

```python
import foghttp
from foghttp.methods import POST


async with foghttp.AsyncClient(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
) as client:
    response = await client.request(
        POST,
        "users",
        headers={"x-trace": "async-example"},
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
```

Sync and async request builders share the same merge and body conflict rules.

## Form Data

Use `data=` for buffered form-urlencoded requests.

```python
import foghttp


with foghttp.Client(base_url="https://api.example.com") as client:
    response = client.post(
        "oauth/token",
        data={
            "grant_type": "client_credentials",
            "scope": ["read", "write"],
        },
    )
    response.raise_for_status()
```

Mappings and repeated pairs are encoded with repeated keys preserved. FogHTTP
adds `content-type: application/x-www-form-urlencoded` for encoded form data
unless the caller already set `content-type`.

Raw `bytes` or `str` passed through `data=` are treated as already encoded
buffered body content, so FogHTTP does not add a semantic content type for
those values.

## Multipart Files

Use `files=` for `multipart/form-data` uploads. `data=` can be combined with
`files=` only when it is a mapping or repeated pairs of form fields.

```python
import foghttp


with foghttp.Client(base_url="https://api.example.com") as client:
    with open("avatar.png", "rb") as avatar:
        response = client.post(
            "profile/avatar",
            data={"description": "profile"},
            files={"file": ("avatar.png", avatar, "image/png")},
        )
    response.raise_for_status()
```

Direct file-like objects and direct stream parts are non-replayable for
method-preserving redirects. Buffered bytes-like file parts are replayable.
Zero-argument stream factories are replayable because FogHTTP asks the factory
for a fresh part for each send attempt. Direct file-like objects passed through
`files=` remain caller-owned and are not closed by FogHTTP. Direct file-like
objects and streams passed through `content=` are request-scope body providers;
FogHTTP closes them after the request attempt.

FogHTTP manages the multipart boundary. If you provide a `content-type` for a
multipart upload, it must be `multipart/form-data` without a `boundary=`
parameter; FogHTTP appends the boundary that matches the encoded body.
Multipart field names, filenames, and part content types are currently limited
to printable ASCII header values. Control characters, bidirectional formatting
controls, and non-ASCII names are rejected before the request is sent.

## Prepared Requests

Use `build_request()` when application code needs to inspect or adjust a request
before sending it.

```python
import foghttp
from foghttp.methods import POST


with foghttp.Client(
    base_url="https://api.example.com/v1",
    headers={"accept": "application/json"},
) as client:
    request = client.build_request(
        POST,
        "users",
        json={"name": "Grace Hopper"},
    )
    request.headers["x-trace"] = "prepared-request"
    response = client.send(request)
    response.raise_for_status()
```

`build_request()` is transport-free: it does not open sockets, create the lazy
Rust client, or consume pool/request slots.

## Body Conflict Matrix

| Combination | Result |
|---|---|
| no body source | no request body |
| `json=None` | no request body |
| `json=False`, `json=0`, `{}`, `[]` | JSON body |
| `content=None` | no request body |
| `content=b""`, `content=""` | empty buffered body |
| `data=None` | no request body |
| `data={}`, `data=[]` | empty form-urlencoded body |
| `data=` mapping or repeated pairs | form-urlencoded body |
| `data=` bytes or string | raw buffered body |
| `files={}`, `files=[]` | empty multipart/form-data body |
| `files=` mapping or repeated pairs | multipart/form-data body |
| `files=` plus mapping or repeated-pair `data=` | multipart body with form fields |
| `files=` plus raw bytes/string `data=` | `TypeError` |
| more than one incompatible source among `json=`, `data=`, `content=`, and `files=` | `ValueError` |
| sync bytes-like iterator `content=` | streamed request body; non-replayable |
| async bytes-like iterator `content=` with `AsyncClient` | streamed request body; non-replayable |
| async byte iterator `content=` with sync `Client` | `TypeError` |
| iterator `data=` | `TypeError` |

Body parameters are part of `request()`, `stream()`, and body-capable method
helpers such as `post()`, `put()`, `patch()`, and `delete()`. The `get()` and
`head()` helpers intentionally do not expose body parameters.

`Content-Length` and `Transfer-Encoding` are transport-managed framing headers
and cannot be set manually. `Content-Type` is semantic and can be set by the
caller. FogHTTP adds `application/json` for `json=`, form-urlencoded content
type for encoded `data=`, and multipart content type with a managed boundary for
`files=` when the caller did not already provide a compatible content type.

Buffered `json=`, `data=`, and byte/string `content=` request bodies are
replayable for the current redirect policy. Streaming and file-backed
`content=` bodies are non-replayable, so method-preserving redirects such as
`307` and `308` fail closed instead of replaying a consumed provider.
Multipart bodies follow the same replayability rule: bytes-like file parts are
replayable, direct file/stream parts are non-replayable, and factory-backed
stream parts are replayable.

Unknown-length streaming bodies use transport-managed HTTP/1.1 framing. Binary
file-like bodies use a known `Content-Length` when FogHTTP can determine the
remaining length safely from regular-file metadata or seek/tell metadata on
objects without a non-regular file descriptor.

## Intentional Differences

FogHTTP is not trying to clone the full `requests`, `httpx`, or `zapros`
surface. Today it is best for JSON/API clients and explicit streaming
upload/download workflows with observable request limits.

Current intentional gaps:

- no cookie jar
- no `auth=` helper
- no streaming decompression helpers yet
- no disabling TLS verification

For these gaps, keep logic outside FogHTTP for now or wait for the planned
feature-specific layer.
