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
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and RFC 10008 `QUERY`
- `base_url` for reusable API clients and relative request paths
- default client headers with per-request overrides
- default client query params with per-request params appended after defaults
- query parameters from mappings, repeated pairs, and raw query strings
- JSON bodies through `json=`
- form-urlencoded bodies through mapping or repeated-pair `data=`
- multipart file uploads through `files=`, optionally combined with mapping or
  repeated-pair `data=` form fields
- raw bytes/text, binary file-like, sync bytes-like iterable, and async bytes-like iterable
  bodies through `content=`
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
- GET/HEAD/POST/QUERY redirects
- HTTPS with default WebPKI roots, explicit custom CA certificate files, and
  custom-only CA trust through `TLSConfig(trust_webpki_roots=False)`
- plain HTTP proxy routing and HTTPS proxy `CONNECT` through explicit `proxy=`
  or `trust_env=True` when the proxy endpoint uses `http://`, plus
  `SSL_CERT_FILE`; see
  [Proxy and trust_env](./proxies.md)
- async request cancellation that aborts the in-flight Rust request
- global/per-origin active request limits, a bounded FIFO pending acquire queue,
  request-slot pressure stats, and stuck request pool diagnostics
- opt-in global/per-origin HTTP/1.1 physical connection caps with separate
  connection-acquire pressure and idle lifecycle diagnostics
- opt-in typed telemetry event hooks for request, redirect, response headers,
  response body, and request completion lifecycle
- opt-in synchronous transport policy hooks with immutable request/response
  snapshots and Rust-owned redirect safety
- opt-in async lifecycle debug snapshots for active async request handles,
  pending transport pressure, strict test checks, and unclosed-client context
- default per-response and aggregate buffered response memory limits
- explicit `close()`/`aclose()` lifecycle for Rust transport and pool resources;
  sync `close()` waits for in-flight sync requests, while async `aclose()`
  cancels in-flight async requests; see [Client lifecycle](./lifecycle.md)
- documented current timeout model for client-level `connect` and per-request
  `pool`/`read`/`write`/`total`; see
  [Timeout model](./timeouts.md)
- shared Tokio runtime by default and opt-in dedicated runtime worker tuning
- reusable HTTP method constants through `foghttp.methods`
- HTTP/1.1 over HTTP and HTTPS

## Current Gaps And Constraints

| Feature | Current behavior |
|---|---|
| CPython wheel ABI | Published wheels use `cp311-abi3`; the release pipeline validates the same native wheel on GIL-enabled CPython 3.11 through 3.14 for each natively runnable OS/architecture target |
| Free-threaded CPython | Not supported by the current `abi3` wheels; PyO3's separate `abi3t` stable ABI starts at Python 3.15 and requires its own adoption and validation decision |
| Streaming response decompression | Not available; buffered responses support transparent decoding |
| Multipart uploads | Available through `files=` for bytes-like parts, binary file-like objects, direct byte streams, and byte-stream factories |
| `files=` | Available; can be combined with mapping or repeated-pair `data=` form fields, but not with raw `data=`, `content=`, or `json=` |
| Multipart header values | Field names, filenames, and part content types are currently limited to printable ASCII; non-ASCII filenames need a later compatibility design |
| Streaming uploads | Available through `content=` for binary file-like objects, sync bytes-like iterables, zero-arg byte-stream factories, and async bytes-like iterables/factories on `AsyncClient`; direct stream/file bodies are non-replayable for method-preserving redirects, while factories can replay by returning a fresh stream |
| Upload typing contracts | Public provider/factory and multipart aliases are available for streaming `content=` and multipart `files=` APIs |
| Cookie jar | `cookies=True` is rejected |
| Plain HTTP proxy routing | Available for `http://` targets through explicit `proxy=` or `trust_env=True` environment config |
| HTTPS proxy `CONNECT` | Available for `https://` targets through explicit `proxy=` or `trust_env=True` when the proxy endpoint itself uses `http://`; TLS is validated against the target host |
| TLS-to-proxy endpoints | `https://proxy.example:443` proxy endpoint URLs are rejected; TLS-to-proxy is not implemented yet |
| Environment proxy redirects | Same-origin redirects can continue; cross-origin redirects under `trust_env=True` proxy policy fail closed until per-hop environment proxy recomputation is implemented |
| Auth helpers | Use manual headers for simple cases |
| Disabling TLS verification | Not available by design; use `TLSConfig` with explicit CA certificates |
| OS trust store integration | Not available; FogHTTP uses bundled WebPKI roots unless `trust_webpki_roots=False` is set |
| HTTP/2 | Not available |
| automatic `Accept-Encoding` negotiation | Not implemented; send `Accept-Encoding` manually when you want compressed responses |
| transport-managed request headers | Safe API rejects manual `Host`, `Content-Length`, `Transfer-Encoding`, `TE`, `Trailer`, `Connection`, `Upgrade`, `Keep-Alive`, `Proxy-Connection`, and `Proxy-Authorization` |
| request body source conflicts | Use one body source among `json=`, `data=`, `content=`, and `files=`; `files=` can include form fields from mapping or repeated-pair `data=` |
| HTTP/2 stream-level connection limits | Physical connection caps apply to the current HTTP/1 connector path; HTTP/2 multiplexed stream limits are planned separately with HTTP/2 support |
| explicit physical connection caps and idle sockets | `Limits.max_connections` defaults to `None`; when explicitly set, tracked idle keep-alive connections count against the cap until reused, closed, or removed by transport pool cleanup |
| per-request connect timeout changes | `Timeouts.connect` configures the Rust connector from client-level settings when transport state is created; per-request `timeout.connect` does not reconfigure the connector |
| separate read/write timeout semantics | `Timeouts.read` is implemented as a buffered and streamed response body progress timeout; `Timeouts.write` is implemented for buffered request body write progress and streaming upload chunk/write progress |
| socket lifecycle telemetry granularity | `TransportStats` and `dump_transport_state()["origins"]` expose opened, open-failed, closed, reused, aborted, idle-timeout eviction, active, and idle tracked connection counters for the current HTTP/1 path; dedicated failed-reuse and close-reason taxonomy are not exposed yet because current connector hooks do not provide a stable reason signal |
| telemetry hook granularity | `TelemetryConfig` currently dispatches Python-level request/response lifecycle events; lower-level Rust pool acquire and connection lifecycle event delivery is planned before Prometheus/OpenTelemetry exporters |
| transport policy hook execution | `TransportPolicyHooks` callbacks are synchronous, inline, non-reentrant, and may run on Rust transport worker threads; `after_response_body` observes only redirect bodies consumed internally, not the final response body returned to the caller |
| diagnostic snapshot transactionality | `stats()`, `dump_transport_state()`, and `dump_pool_diagnostics()` include `schema_version` and a monotonic `snapshot_sequence`, but the `dump_*` APIs remain diagnostic snapshots rather than lock-protected SLA transactions; use `stats()` for alert-oriented low-cardinality metrics |

## Practical Guidance

Use FogHTTP today when:

- you control the API or know its behavior well
- responses are small enough to buffer in memory or can be consumed through the
  bytes/text/line streaming API; line streaming has a bounded per-line buffer by
  default
- requests are JSON-heavy, use small form-urlencoded bodies, multipart file
  uploads, or explicit streaming upload bodies
- redirects are simple and do not require cookie jar or auth helper integration
- sync and async clients with explicit lifecycle are enough
- async request cancellation and sync/async stream cleanup behavior are useful
- global/per-origin request-slot backpressure and opt-in global/per-host
  physical connection caps are enough for your resource control needs
- you can reuse clients instead of creating many short-lived transport and pool
  instances once requests start flowing

Wait before using FogHTTP when:

- you need transparent streaming decompression
- you need SOCKS, PAC, WPAD, or platform proxy discovery
- you rely on cookies across requests
- you need per-request connect timeout reconfiguration
- you need automatic compression negotiation instead of manual
  `Accept-Encoding`
- you need HTTP/2 multiplexed stream limits
- you need to share one async client across multiple event loops

## Error Surface

Network and protocol failures map to `RequestError`. Pool acquire timeout and
queue-full conditions map to `PoolTimeout`. Response body progress timeout maps
to `ReadTimeout` for buffered responses and streamed body chunks. Buffered and
streamed request body write progress timeout maps to `WriteTimeout`. The broader
buffered transport deadline maps to the base `TimeoutError` with phase-aware
diagnostics; for streaming responses it covers acquire, redirects, and response
headers before the stream is returned. Dedicated connect timeout exception mapping is
reserved for later timeout work. See
[Timeout model](./timeouts.md) for the current behavior.
