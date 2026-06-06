# Security Policy

FogHTTP is a Rust-powered HTTP client for Python services. Security work is
part of the core project scope because the client handles network input, TLS
trust, redirects, request bodies, response bodies, credentials, cancellation,
and resource limits.

## Supported Versions

FogHTTP is currently pre-`0.5.0`, and backward compatibility is not guaranteed.
Security fixes are handled on a best-effort basis for the active development
line and the latest published release.

| Version | Security support |
|---|---|
| `main` | Active security fixes land here first |
| latest release | Best-effort fixes and patch releases |
| older releases | Not guaranteed |

If you are using an older release and believe a vulnerability affects it,
please report it anyway. The maintainer will decide whether a backport or a new
release is the safest path.

## Reporting a Vulnerability

Please do not open a public GitHub issue for a suspected vulnerability.

Preferred reporting channels:

1. Use GitHub private vulnerability reporting for the repository, if it is
   available.
2. If private reporting is not available, contact the maintainer through GitHub
   without posting vulnerability details publicly:
   - maintainer: [GefMar](https://github.com/GefMar)
   - coordination channel:
     [GitHub Discussions](https://github.com/AmberFog/foghttp/discussions)

If you need to use GitHub Discussions to start coordination, keep the public
message minimal. Do not include exploit details, proof-of-concept code, secrets,
private certificates, production tokens, logs with sensitive data, or customer
information in the public post.

After a private or otherwise appropriate reporting path is established, please
include as much of the following as you can:

- affected FogHTTP version or commit
- Python version, operating system, and platform
- whether the issue affects `Client`, `AsyncClient`, or both
- a minimal proof of concept or reproduction steps
- expected impact and likely attack scenario
- whether the issue is already public
- any logs or diagnostics with secrets removed

Do not send live credentials, private certificates, production tokens, or
customer data. Redacted examples are enough.

## What Counts as Security-Sensitive

The following areas are especially security-sensitive in FogHTTP:

- TLS certificate verification and custom CA trust boundaries
- accidental support for verification-free HTTPS
- redirect behavior across origins or from HTTPS to HTTP
- forwarding of `Authorization`, `Proxy-Authorization`, `Cookie`, `Origin`, or
  `Referer`
- request body replay across origins
- URL credentials, token-like query parameters, or secrets in repr/error output
- sensitive header redaction
- request or response body leakage in diagnostics
- SSRF-related behavior in redirects, URL normalization, proxy support,
  `trust_env` environment configuration, or future environment-driven behavior
- header smuggling or unsafe manual framing headers
- decompression, buffering, and response-body memory limits
- denial of service through connection, request, pending queue, runtime, or
  response memory exhaustion
- cancellation, close, timeout, or runtime teardown bugs that leak tasks,
  sockets, permits, or poisoned pooled connections
- panics, aborts, or undefined behavior caused by untrusted input

## Current Security Design

FogHTTP currently makes several conservative choices:

- HTTPS certificates are verified by default.
- `verify=False` is intentionally not supported.
- TLS trust can use bundled WebPKI roots, WebPKI plus explicit custom CA files,
  or custom-only CA files.
- Redirects are disabled by default.
- Cross-origin redirects strip sensitive headers.
- HTTPS-to-HTTP redirects are blocked.
- Cross-origin `307` and `308` redirects do not replay buffered request bodies.
- Transport-managed framing headers such as `Host`, `Content-Length`, and
  `Transfer-Encoding` are rejected through the safe request API.
- URL credentials, common token query parameters, sensitive headers, and body
  bytes are redacted from debug and error surfaces.
- Buffered responses are limited by per-response and aggregate memory budgets.
- Request concurrency is bounded by global and per-origin active request limits
  and a pending request limit.

Security reports that weaken any of these guarantees are high priority.

## Coordinated Disclosure

The maintainer will make a best-effort attempt to:

- acknowledge the report within a reasonable time
- confirm the affected versions or commits
- keep the reporter updated on fix progress
- credit the reporter if they want credit
- publish a clear advisory or release note once a fix is available

Please give the project time to investigate and release a fix before publishing
full exploit details.

## Out of Scope

The following are usually out of scope unless they demonstrate a concrete
FogHTTP vulnerability:

- attacks that require arbitrary code execution in the caller process
- reports about unsupported features such as proxy transport behavior, cookie
  jar behavior, multipart uploads, or HTTP/2 unless the current code exposes
  unsafe behavior
- denial-of-service reports that ignore documented response and request limits
- issues caused only by intentionally disabling security in user application
  code outside FogHTTP

When in doubt, report the issue privately. It is better to triage a false
positive privately than to disclose a real vulnerability by accident.
