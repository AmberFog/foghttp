---
layout: "home"

hero:
  name: "FogHTTP"
  text: "Rust-powered HTTP client for Python"
  tagline: "Buffered JSON and form requests, streaming and multipart uploads, sync and async response streaming, transparent response decoding, base URL clients, default headers and params, sync and async APIs, redirects, custom CA certificates, cancellation, and observable request limits with pool diagnostics."

features:
  - title: "Rust transport"
    details: "The HTTP core is implemented in Rust on top of hyper, while the public API stays Python-first."

  - title: "Sync and async"
    details: "Use Client in scripts and workers, or AsyncClient for high-concurrency asyncio workloads."

  - title: "Focused MVP"
    details: "FogHTTP is intentionally small today: buffered responses with gzip/deflate/br decoding, sync and async bytes/text/line streaming, JSON, form-urlencoded data, streaming and multipart uploads, base URL clients, default headers and params, redirects, prepared requests, async cancellation, global and per-origin request limits, and request metadata."
---

# FogHTTP Documentation

FogHTTP is currently an MVP. It is already useful for controlled HTTP workloads
that use buffered request/response bodies, JSON and form APIs, streaming or
multipart uploads, explicit client lifecycle, and predictable redirect behavior.

## Positioning

FogHTTP is an observable, high-concurrency Rust-powered transport for Python
services. It is not trying to become a full browser-like client or a complete
replacement for mature general-purpose clients. The goal is a small, explicit,
fast transport layer for Python applications that need predictable behavior
under concurrency.

FogHTTP is designed around a few engineering priorities:

- keep the public API Python-first and easy to type, inspect, and test
- use Rust and `hyper` where transport performance and runtime control matter
- make lifecycle, cancellation, redirects, request backpressure, and request
  metadata visible instead of implicit
- stay focused on production service workloads before expanding into broader
  feature parity

## Key Advantages

- one API shape for sync scripts, workers, and asyncio services
- Rust-backed HTTP/1.1 transport with explicit runtime ownership
- buffered JSON, form, and bytes workflows that are simple to reason about
- transparent `gzip`, `deflate`, and `br` decoding for buffered responses
- sync and async bytes/text/line response streaming with explicit
  context-managed lifecycle
- graceful sync `close()` that waits for in-flight sync requests
- async cancellation that aborts in-flight Rust requests
- redirect history and final request metadata for debugging
- HTTPS with default WebPKI roots, explicit custom CA certificates, and
  custom-only CA trust
- global and per-origin request backpressure with per-origin acquire pressure
  snapshots and stuck request diagnostics for operational visibility
- opt-in typed telemetry event hooks with redacted request/response lifecycle
  events
- versioned telemetry snapshots that separate alert-oriented stats from
  diagnostic dump APIs
- opt-in async lifecycle debug snapshots for tests, staging, and incident
  diagnostics

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Start Here

- [Quickstart](./quickstart.md)
- [Request builder compatibility](./request-builder.md)
- [Client lifecycle](./lifecycle.md)
- [Timeout model](./timeouts.md)
- [Upload typing contracts](./upload-types.md)
- [Telemetry contract](./telemetry.md)
- [Response streaming](./streaming.md)
- [TLS trust](./tls.md)
- [Proxy and trust_env](./proxies.md)
- [Use cases](./use-cases.md)
- [Redirects](./redirects.md)
- [Limitations](./limitations.md)
- [Benchmarks](./benchmarks.md)
- [PyO3 boundary notes](./pyo3-boundary.md)

## Good Fit Today

- internal service-to-service API clients
- async fan-out over JSON HTTP APIs
- sync CLI scripts and background workers
- redirect-aware requests with final URL and history
- cancellable buffered async requests
- bounded sync and async response streaming
- prepared requests that can be inspected before sending
- simple benchmarks against other buffered HTTP clients

## Key Features

- sync `Client` and async `AsyncClient`
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`
- `base_url` for reusable API clients and relative request paths
- default client headers and query params for reusable API clients
- query params with repeated keys, JSON, form-urlencoded data, buffered
  bytes/text bodies, file-like bodies, streaming bytes-like iterables, and
  multipart `files=` uploads
- transparent `gzip`, `deflate`, and `br` decoding for buffered responses
- sync and async bytes/text/line response streaming with context-managed cleanup
- response status flags for success, redirects, and client/server errors
- prepared `Request` objects with `build_request()` and `send()`
- public upload typing contracts for streaming request bodies and multipart
  `files=` providers
- case-insensitive `Headers` with repeated value support
- safe policy for transport-managed request headers
- redacted repr/error surfaces for sensitive headers, URL credentials,
  token-like URL params, and buffered body bytes
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST redirects with final URL, history, and conservative replay policy
- HTTPS with default WebPKI roots, explicit custom CA certificates, and
  custom-only CA trust
- documented lazy transport creation, graceful sync close, async request
  cancellation, and explicit client lifecycle
- documented buffered timeout model with pool and total deadline behavior
- global active request limits, per-origin active request limits, pending
  acquire limits, per-origin acquire pressure snapshots, and stuck request
  diagnostics
- opt-in typed telemetry event hooks for request, redirect, response headers,
  response body, and request completion lifecycle
- versioned telemetry snapshot metadata for `stats()`, `dump_transport_state()`,
  and `dump_pool_diagnostics()`
- opt-in async lifecycle debug mode for active request snapshots and strict
  leak checks
- HTTP proxy routing and HTTPS `CONNECT` tunnelling through explicit `proxy=` or
  `trust_env=True` (`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`) when the proxy
  endpoint uses `http://`, with target-host TLS validation for tunnelled HTTPS
- default per-response and aggregate buffered response body limits
- grouped HTTP status constants and reusable HTTP method constants

## Not Yet

FogHTTP does not yet implement cookies, HTTP/2, automatic `Accept-Encoding`
negotiation, streaming decompression, or advanced authentication helpers.
`trust_env` supports HTTP proxy routing, HTTPS
`CONNECT` tunnelling through `http://` proxy endpoints, and `SSL_CERT_FILE`.
Disabling TLS verification is intentionally not supported. See
[Limitations](./limitations.md) for details.
