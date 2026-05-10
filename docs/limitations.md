# Limitations

FogHTTP is an MVP. It can already be useful, but it is not trying to be a full
`httpx` replacement yet.

## Compatibility Policy

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Supported Today

- sync `Client`
- async `AsyncClient`
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`
- query parameters from mappings
- JSON bodies through `json=`
- raw bytes/text bodies through `content=`
- buffered responses
- `response.text`, `response.json()`, `response.raise_for_status()`
- lightweight `response.request`
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated values
- normalized `URL` with origin comparison and relative joins
- redirect history
- GET/HEAD/POST redirects
- async request cancellation that aborts the in-flight Rust request
- global pool acquire limit, pending acquire limit, and basic pool stats
- explicit `close()`/`aclose()` lifecycle for Rust runtime and pool resources
- advanced `runtime_workers` tuning for the per-client Tokio runtime
- HTTP/1.1 over HTTP and HTTPS

## Not Implemented Yet

| Feature | Current behavior |
|---|---|
| Streaming responses | Not available; responses are fully buffered |
| Streaming uploads | Not available; request bodies are buffered |
| Multipart uploads | Not available |
| `data=` form encoding | Not available |
| `files=` | Not available |
| Cookie jar | `cookies=True` is rejected |
| Proxy support | `trust_env=True` is rejected |
| Auth helpers | Use manual headers for simple cases |
| HTTP/2 | Not available |
| Compression decoding | Not available |
| `base_url` | Not available |
| default client headers | Not available |
| active per-origin connection limits | `max_connections_per_host` is accepted but is not a full active per-origin limit yet |
| separate read/write timeout semantics | `Timeouts.read` and `Timeouts.write` exist, but buffered requests are still governed by total timeout behavior |

## Practical Guidance

Use FogHTTP today when:

- you control the API or know its behavior well
- responses are small enough to buffer in memory
- requests are JSON-heavy
- redirects are simple and do not require browser-like cookie/auth policy
- sync and async clients with explicit lifecycle are enough
- async request cancellation behavior is useful, but you do not need streaming
  cancellation semantics yet
- global connection backpressure is enough for your pool needs
- you can reuse clients instead of creating many short-lived runtime instances

Wait before using FogHTTP when:

- you download large files
- you upload large files
- you need proxy behavior from environment variables
- you rely on cookies across requests
- you need multipart form-data
- you need mature timeout semantics for connect/read/write separately
- you need strict active per-host connection limits

## Error Surface

The public exception hierarchy exists, but some transport errors and timeout
causes are still coarse. The timeout model and network error mapping are planned
to become more precise.
