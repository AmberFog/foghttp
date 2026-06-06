# Limitations

FogHTTP is an MVP. It can already be useful, but it is not trying to be a full
`httpx` replacement yet.

For request-parameter compatibility with common Python HTTP clients, see
[Request builder compatibility](./request-builder.md).

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
- form-urlencoded bodies through mapping or repeated-pair `data=`
- raw bytes/text bodies through `content=`
- buffered responses
- transparent `gzip`, `deflate`, and `br` decoding for buffered responses
- sync response streaming through `Client.stream()`
- async response streaming through `AsyncClient.stream()`
- `response.text`, `response.json()`, response status flags, and
  `response.raise_for_status()`
- lightweight `response.request`
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated values
- response header bytes exposed as Latin-1 strings, including obs-text values
- normalized `URL` with origin comparison and relative joins
- redirect history
- GET/HEAD/POST redirects
- HTTPS with default WebPKI roots, explicit custom CA certificate files, and
  custom-only CA trust through `TLSConfig(trust_webpki_roots=False)`
- plain HTTP proxy routing through explicit `proxy=` or `trust_env=True`,
  plus `SSL_CERT_FILE`; see [Proxy and trust_env](./proxies.md)
- async request cancellation that aborts the in-flight Rust request
- global active request limit, per-origin active request limit, pending acquire
  limit, request stats, and stuck request pool diagnostics
- opt-in typed telemetry event hooks for request, redirect, response headers,
  response body, and request completion lifecycle
- opt-in async lifecycle debug snapshots for active async request handles,
  pending transport pressure, strict test checks, and unclosed-client context
- default per-response and aggregate buffered response memory limits
- explicit `close()`/`aclose()` lifecycle for Rust runtime and pool resources;
  sync `close()` waits for in-flight sync requests, while async `aclose()`
  cancels in-flight async requests; see [Client lifecycle](./lifecycle.md)
- documented current timeout model for client-level `connect`, per-request
  `pool`/`read`/`total`, and reserved `write`; see
  [Timeout model](./timeouts.md)
- advanced `runtime_workers` tuning for the per-client Tokio runtime
- reusable HTTP method constants through `foghttp.methods`
- HTTP/1.1 over HTTP and HTTPS

## Not Implemented Yet

| Feature | Current behavior |
|---|---|
| Streaming response decompression | Not available; buffered responses support transparent decoding |
| Streaming uploads | Not available; request bodies are buffered |
| Multipart uploads | Not available |
| `files=` | Reserved in the body matrix; not available yet |
| Cookie jar | `cookies=True` is rejected |
| Plain HTTP proxy routing | Available for `http://` targets through explicit `proxy=` or `trust_env=True` environment config |
| HTTPS proxy `CONNECT` | Not available yet; proxied `https://` targets fail closed instead of using direct transport |
| Auth helpers | Use manual headers for simple cases |
| Disabling TLS verification | Not available by design; use `TLSConfig` with explicit CA certificates |
| OS trust store integration | Not available; FogHTTP uses bundled WebPKI roots unless `trust_webpki_roots=False` is set |
| HTTP/2 | Not available |
| automatic `Accept-Encoding` negotiation | Not implemented; send `Accept-Encoding` manually when you want compressed responses |
| transport-managed request headers | Safe API rejects manual `Host`, `Content-Length`, `Transfer-Encoding`, `TE`, `Trailer`, `Connection`, `Upgrade`, `Keep-Alive`, `Proxy-Connection`, and `Proxy-Authorization` |
| request body source conflicts | Only one body source can be passed today: `json=`, `data=`, or `content=` |
| true active connection-level limits | `max_active_requests_per_origin` limits buffered request slots; socket lifecycle telemetry is observable, but FogHTTP does not yet expose separate physical connection limits |
| per-request connect timeout changes | `Timeouts.connect` configures the Rust connector from client-level settings when transport state is created; per-request `timeout.connect` does not reconfigure the connector |
| separate read/write timeout semantics | `Timeouts.read` is implemented as a buffered and streamed response body progress timeout; `Timeouts.write` is reserved for later streaming upload/body work |
| socket lifecycle telemetry granularity | `TransportStats` and `dump_transport_state()["origins"]` expose opened, open-failed, closed, reused, aborted, active, and idle tracked connection counters for the current HTTP/1 path; these are connector/lifecycle diagnostics, not a stable public view into Hyper's private pool internals |
| telemetry hook granularity | `TelemetryConfig` currently dispatches Python-level request/response lifecycle events; lower-level Rust pool acquire and connection lifecycle event delivery is planned before Prometheus/OpenTelemetry exporters |
| diagnostic snapshot transactionality | `stats()`, `dump_transport_state()`, and `dump_pool_diagnostics()` include `schema_version` and a monotonic `snapshot_sequence`, but the `dump_*` APIs remain diagnostic snapshots rather than lock-protected SLA transactions; use `stats()` for alert-oriented low-cardinality metrics |

## Practical Guidance

Use FogHTTP today when:

- you control the API or know its behavior well
- responses are small enough to buffer in memory or can be consumed through the
  bytes/text/line streaming API; line streaming has a bounded per-line buffer by
  default
- requests are JSON-heavy or use small form-urlencoded bodies
- redirects are simple and do not require cookie jar or auth helper integration
- sync and async clients with explicit lifecycle are enough
- async request cancellation and sync/async stream cleanup behavior are useful
- global and per-origin request-slot backpressure is enough for your
  resource control needs
- you can reuse clients instead of creating many short-lived runtime instances
  once requests start flowing

Wait before using FogHTTP when:

- you need transparent streaming decompression
- you upload large files
- you need HTTPS proxy `CONNECT`, SOCKS, PAC, WPAD, or platform proxy discovery
- you rely on cookies across requests
- you need multipart form-data or large uploads
- you need per-request connect timeout reconfiguration or request-body write
  timeout semantics
- you need automatic compression negotiation instead of manual
  `Accept-Encoding`
- you need strict active per-host connection limits
- you need to share one async client across multiple event loops

## Error Surface

Network and protocol failures map to `RequestError`. Pool acquire timeout and
queue-full conditions map to `PoolTimeout`. Response body progress timeout maps
to `ReadTimeout` for buffered responses and streamed body chunks. The broader
buffered transport deadline maps to the base `TimeoutError` with phase-aware
diagnostics; for streaming it covers acquire, redirects, and response headers
before the stream is returned. Dedicated connect/write timeout exception
mappings are reserved for later timeout work. See
[Timeout model](./timeouts.md) for the current behavior.
