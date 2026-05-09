---
layout: "home"

hero:
  name: "FogHTTP"
  text: "Rust-powered HTTP client for Python"
  tagline: "Buffered JSON requests, sync and async clients, redirects, and observable pooling."

features:
  - title: "Rust transport"
    details: "The HTTP core is implemented in Rust on top of hyper, while the public API stays Python-first."

  - title: "Sync and async"
    details: "Use Client in scripts and workers, or AsyncClient for high-concurrency asyncio workloads."

  - title: "Focused MVP"
    details: "FogHTTP is intentionally small today: buffered responses, JSON, redirects, prepared requests, global pool limits, and request metadata."
---

# FogHTTP Documentation

FogHTTP is currently an MVP. It is already useful for controlled HTTP workloads
that use buffered request/response bodies, JSON APIs, explicit client lifecycle,
and predictable redirect behavior.

Until version `0.5.0`, backward compatibility is not guaranteed. I will still
try to keep public interfaces stable and avoid unnecessary breaking changes.

## Start Here

- [Quickstart](./quickstart.md)
- [Use cases](./use-cases.md)
- [Redirects](./redirects.md)
- [Limitations](./limitations.md)

## Good Fit Today

- internal service-to-service API clients
- async fan-out over JSON HTTP APIs
- sync CLI scripts and background workers
- redirect-aware requests with final URL and history
- prepared requests that can be inspected before sending
- simple benchmarks against other buffered HTTP clients

## Not Yet

FogHTTP does not yet implement streaming bodies, cookies, multipart uploads,
proxy support, `trust_env`, HTTP/2, or advanced authentication helpers. See
[Limitations](./limitations.md) for details.
