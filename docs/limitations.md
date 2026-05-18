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
- `base_url` for reusable API clients and relative request paths
- default client headers with per-request overrides
- default client query params with per-request params appended after defaults
- query parameters from mappings, repeated pairs, and raw query strings
- JSON bodies through `json=`
- raw bytes/text bodies through `content=`
- buffered responses
- `response.text`, `response.json()`, response status flags, and
  `response.raise_for_status()`
- lightweight `response.request`
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated values
- normalized `URL` with origin comparison and relative joins
- redirect history
- GET/HEAD/POST redirects
- HTTPS with default WebPKI roots and explicit custom CA certificate files
- async request cancellation that aborts the in-flight Rust request
- global active request limit, per-origin active request limit, pending acquire
  limit, and basic request stats
- default `max_response_body_size` limit for buffered response memory safety
- explicit `close()`/`aclose()` lifecycle for Rust runtime and pool resources;
  sync `close()` waits for in-flight sync requests, while async `aclose()`
  cancels in-flight async requests; see [Client lifecycle](./lifecycle.md)
- documented current timeout model for client-level `connect`, per-request
  `pool`/`total`, and reserved `read`/`write`; see
  [Timeout model](./timeouts.md)
- advanced `runtime_workers` tuning for the per-client Tokio runtime
- reusable HTTP method constants through `foghttp.methods`
- HTTP/1.1 over HTTP and HTTPS

## Not Implemented Yet

| Feature | Current behavior |
|---|---|
| Streaming responses | Not available; responses are fully buffered |
| Streaming uploads | Not available; request bodies are buffered |
| Multipart uploads | Not available |
| `data=` form encoding | Reserved in the body matrix; not available yet |
| `files=` | Reserved in the body matrix; not available yet |
| Cookie jar | `cookies=True` is rejected |
| Proxy support | `trust_env=True` is rejected |
| Auth helpers | Use manual headers for simple cases |
| Disabling TLS verification | Not available; use `TLSConfig` with explicit CA certificates |
| HTTP/2 | Not available |
| Compression decoding | Not available |
| transport-managed request headers | Safe API rejects manual `Host`, `Content-Length`, `Transfer-Encoding`, `TE`, `Trailer`, `Connection`, `Upgrade`, `Keep-Alive`, and `Proxy-Connection` |
| request body source conflicts | Only one body source can be passed today: `json=` or `content=` |
| true active connection-level limits | `max_active_requests_per_origin` limits buffered request slots; physical TCP connection-level accounting is not exposed yet |
| per-request connect timeout changes | `Timeouts.connect` configures the Rust connector from client-level settings when transport state is created; per-request `timeout.connect` does not reconfigure the connector |
| separate read/write timeout semantics | `Timeouts.read` and `Timeouts.write` exist, but separate body read/write deadlines are reserved for later streaming/body work |

## Practical Guidance

Use FogHTTP today when:

- you control the API or know its behavior well
- responses are small enough to buffer in memory or bounded by
  `max_response_body_size`
- requests are JSON-heavy
- redirects are simple and do not require cookie jar or auth helper integration
- sync and async clients with explicit lifecycle are enough
- async request cancellation behavior is useful, but you do not need streaming
  cancellation semantics yet
- global and per-origin buffered request backpressure is enough for your
  resource control needs
- you can reuse clients instead of creating many short-lived runtime instances
  once requests start flowing

Wait before using FogHTTP when:

- you download large files and need streaming instead of buffered fail-fast
  limits
- you upload large files
- you need proxy behavior from environment variables
- you rely on cookies across requests
- you need multipart form-data
- you need per-request connect timeout reconfiguration or mature read/write
  timeout semantics
- you need strict active per-host connection limits
- you need to share one async client across multiple event loops

## Error Surface

Network and protocol failures map to `RequestError`. Pool acquire timeout and
queue-full conditions map to `PoolTimeout`. The broader buffered transport
deadline maps to the base `TimeoutError`. Dedicated connect/read/write timeout
exception mappings are reserved for later timeout work. See
[Timeout model](./timeouts.md) for the current behavior.
