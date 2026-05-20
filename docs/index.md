---
layout: "home"

hero:
  name: "FogHTTP"
  text: "Rust-powered HTTP client for Python"
  tagline: "Buffered JSON and form requests, base URL clients, default headers and params, sync and async APIs, redirects, custom CA certificates, cancellation, and observable request limits."

features:
  - title: "Rust transport"
    details: "The HTTP core is implemented in Rust on top of hyper, while the public API stays Python-first."

  - title: "Sync and async"
    details: "Use Client in scripts and workers, or AsyncClient for high-concurrency asyncio workloads."

  - title: "Focused MVP"
    details: "FogHTTP is intentionally small today: buffered responses, JSON, form-urlencoded data, base URL clients, default headers and params, redirects, prepared requests, async cancellation, global and per-origin request limits, and request metadata."
---

# FogHTTP Documentation

FogHTTP is currently an MVP. It is already useful for controlled HTTP workloads
that use buffered request/response bodies, JSON and form APIs, explicit client
lifecycle, and predictable redirect behavior.

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
- graceful sync `close()` that waits for already-started sync requests
- async cancellation that aborts in-flight Rust requests
- redirect history and final request metadata for debugging
- HTTPS with default WebPKI roots and explicit custom CA certificates
- global and per-origin request backpressure with stats for operational
  visibility

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Start Here

- [Quickstart](./quickstart.md)
- [Request builder compatibility](./request-builder.md)
- [Client lifecycle](./lifecycle.md)
- [Timeout model](./timeouts.md)
- [Use cases](./use-cases.md)
- [Redirects](./redirects.md)
- [Limitations](./limitations.md)
- [Benchmarks](./benchmarks.md)

## Good Fit Today

- internal service-to-service API clients
- async fan-out over JSON HTTP APIs
- sync CLI scripts and background workers
- redirect-aware requests with final URL and history
- cancellable buffered async requests
- prepared requests that can be inspected before sending
- simple benchmarks against other buffered HTTP clients

## Key Features

- sync `Client` and async `AsyncClient`
- `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`
- `base_url` for reusable API clients and relative request paths
- default client headers and query params for reusable API clients
- query params with repeated keys, JSON, form-urlencoded data, and buffered
  bytes/text bodies
- response status flags for success, redirects, and client/server errors
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated value support
- safe policy for transport-managed request headers
- redacted repr/error surfaces for sensitive headers, URL credentials,
  token-like URL params, and buffered body bytes
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST redirects with final URL, history, and conservative replay policy
- HTTPS with default WebPKI roots and explicit custom CA certificates
- documented lazy transport creation, graceful sync close, async request
  cancellation, and explicit client lifecycle
- documented buffered timeout model with pool and total deadline behavior
- global active request limits, per-origin active request limits, pending
  acquire limits, and basic stats
- default per-response and aggregate buffered response body limits
- grouped HTTP status constants and reusable HTTP method constants

## Not Yet

FogHTTP does not yet implement streaming bodies, cookies, multipart uploads,
proxy support, `trust_env`, `verify=False`, HTTP/2, or advanced authentication
helpers. See [Limitations](./limitations.md) for details.
