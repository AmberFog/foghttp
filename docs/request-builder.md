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
| `content` | Supported | Accepts buffered `bytes` or `str`. Strings are encoded as UTF-8. No semantic content type is added. |
| `data` | Supported | Mappings and repeated pairs are encoded as `application/x-www-form-urlencoded`. Raw `bytes` or `str` are sent as buffered body content without adding a semantic content type. |
| `files` | Reserved | Planned for multipart uploads. Not accepted yet. |
| `auth` | Planned | Use explicit `Authorization` headers for simple static tokens. |
| cookies/session jar | Planned | `cookies=True` is rejected today. |
| proxy / `trust_env` | Planned | `trust_env=True` is rejected today. |
| `timeout` | Partly supported | Per-request `pool` and `total` timeouts are supported. Per-request `connect` does not reconfigure the connector. `read` and `write` are reserved. |
| `follow_redirects` | Supported | Client-level setting. GET/HEAD/POST redirects use conservative security rules. |
| prepared request | Supported | Use `build_request()` and `send()`. Building a request does not create transport state. |

## Merge Order

FogHTTP applies request values in this order:

| Area | Order |
|---|---|
| URL | `base_url` resolution, request URL query, client params, per-request params |
| Headers | client headers, future auth-managed headers, per-request headers |
| Body | exactly one body source: `json=`, `data=`, or `content=` |

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
| more than one of `json=`, `data=`, `content=` | `ValueError` |
| iterator or async iterator `content=` | `TypeError` |
| iterator `data=` | `TypeError` |
| `files=` | not accepted yet |

`Content-Length` and `Transfer-Encoding` are transport-managed framing headers
and cannot be set manually. `Content-Type` is semantic and can be set by the
caller; FogHTTP only adds `application/json` for `json=` when the caller did not
already provide a content type.

Buffered `json=`, `data=`, and `content=` request bodies are replayable for the
current redirect policy. Future streaming uploads will need an explicit
non-replayable body contract.

## Intentional Differences

FogHTTP is not trying to clone the full `requests`, `httpx`, or `zapros`
surface. Today it is best for buffered JSON/API clients with explicit lifecycle
and observable request limits.

Current intentional gaps:

- no `files=` multipart uploads yet
- no cookie jar
- no `auth=` helper
- no proxy or `trust_env` behavior
- no streaming request or response body API yet
- no disabling TLS verification

For these gaps, keep logic outside FogHTTP for now or wait for the planned
feature-specific layer.
