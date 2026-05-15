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
- global active request limit, per-origin active request limit, pending acquire
  limit, and basic request stats
- optional `max_response_body_size` limit for buffered response memory safety
- explicit `close()`/`aclose()` lifecycle for Rust runtime and pool resources;
  sync `close()` waits for in-flight sync requests, while async `aclose()`
  cancels in-flight async requests
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
| true active connection-level limits | `max_active_requests_per_origin` limits buffered request slots; physical TCP connection-level accounting is not exposed yet |
| per-request connect timeout changes | `Timeouts.connect` configures the Rust connector when transport state is created; per-request connect timeout changes do not reconfigure an existing client |
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
- global and per-origin buffered request backpressure is enough for your
  resource control needs
- you can reuse clients instead of creating many short-lived runtime instances

Wait before using FogHTTP when:

- you download large files
- you upload large files
- you need proxy behavior from environment variables
- you rely on cookies across requests
- you need multipart form-data
- you need per-request connect timeout reconfiguration or mature read/write
  timeout semantics
- you need strict active per-host connection limits

## Error Surface

Network and protocol failures map to `RequestError`. Pool acquire timeout and
queue-full conditions map to `PoolTimeout`. Whole buffered request deadline
expiration maps to the base `TimeoutError`. Dedicated read/write timeout
exceptions are reserved for later body/streaming work.
