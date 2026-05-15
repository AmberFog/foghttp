---
layout: "home"

hero:
  name: "FogHTTP"
  text: "Rust-powered HTTP client for Python"
  tagline: "Buffered JSON requests, sync and async clients, redirects, cancellation, and observable request limits."

features:
  - title: "Rust transport"
    details: "The HTTP core is implemented in Rust on top of hyper, while the public API stays Python-first."

  - title: "Sync and async"
    details: "Use Client in scripts and workers, or AsyncClient for high-concurrency asyncio workloads."

  - title: "Focused MVP"
    details: "FogHTTP is intentionally small today: buffered responses, JSON, redirects, prepared requests, async cancellation, global and per-origin request limits, and request metadata."
---

# FogHTTP Documentation

FogHTTP is currently an MVP. It is already useful for controlled HTTP workloads
that use buffered request/response bodies, JSON APIs, explicit client lifecycle,
and predictable redirect behavior.

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
- buffered JSON and bytes workflows that are simple to reason about
- async cancellation that aborts in-flight Rust requests
- redirect history and final request metadata for debugging
- global and per-origin request backpressure with stats for operational
  visibility

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Start Here

- [Quickstart](./quickstart.md)
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
- query params, JSON bodies, and buffered bytes/text bodies
- prepared `Request` objects with `build_request()` and `send()`
- case-insensitive `Headers` with repeated value support
- normalized `URL` model with origin comparison and relative joins
- GET/HEAD/POST redirects with final URL and history
- async request cancellation and explicit client lifecycle
- global active request limits, per-origin active request limits, pending
  acquire limits, and basic stats
- optional buffered response body size limit
- grouped HTTP status constants

## Not Yet

FogHTTP does not yet implement streaming bodies, cookies, multipart uploads,
proxy support, `trust_env`, HTTP/2, or advanced authentication helpers. See
[Limitations](./limitations.md) for details.
