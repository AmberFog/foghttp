# Proxy and trust_env

FogHTTP has a `trust_env` resolver foundation, but HTTP proxy routing is not
implemented yet. The resolver snapshots and validates environment configuration
when the client is created so future proxy transport work can use a typed,
redacted decision model without reading environment variables on each request.

## Current Behavior

`trust_env=False` remains the default.

With `trust_env=True`, FogHTTP currently:

- accepts the client option
- reads supported environment variables once during client configuration
- validates proxy URLs and `NO_PROXY` rules
- redacts proxy credentials in debug-facing representations
- maps `SSL_CERT_FILE` to `TLSConfig` when no explicit `tls=` is passed

It does not yet:

- route HTTP requests through a proxy
- tunnel HTTPS requests through `CONNECT`
- support SOCKS, PAC, WPAD, browser proxy stores, or platform proxy discovery
- read proxy environment variables on every request
- use `SSL_CERT_DIR`
- disable TLS verification through environment variables

## Supported Environment Variables

| Variable | Current behavior |
|---|---|
| `HTTP_PROXY` / `http_proxy` | Parsed for future HTTP proxy decisions. Uppercase `HTTP_PROXY` is ignored when `REQUEST_METHOD` is set to avoid HTTPoxy-style CGI leakage. |
| `HTTPS_PROXY` / `https_proxy` | Parsed for future HTTPS proxy decisions. |
| `ALL_PROXY` / `all_proxy` | Parsed as fallback when no scheme-specific proxy is set. |
| `NO_PROXY` / `no_proxy` | Parsed as bypass rules for the selected target origin. |
| `SSL_CERT_FILE` / `ssl_cert_file` | Converted to `TLSConfig(ca_certificates=(...))` if `tls=` is not passed explicitly. |
| `SSL_CERT_DIR` | Ignored. Directory trust-store loading is not implemented. |

Lowercase proxy variables win over uppercase variants for the same setting.
Scheme-specific proxy variables win over `ALL_PROXY`.

Proxy URLs may include userinfo for future proxy authentication support. FogHTTP
keeps the canonical proxy endpoint without userinfo and exposes credentials only
through internal typed fields with redacted debug representations.

## NO_PROXY Rules

FogHTTP supports a focused `NO_PROXY` subset:

- wildcard `*`
- exact hosts
- domain suffixes such as `example.com`, `.example.com`, or `*.example.com`
  matching both the apex host and subdomains, but not lookalikes such as
  `badexample.com`
- optional ports such as `example.com:8443`; ports must be in the `1..65535`
  range
- `localhost`
- IPv4 addresses
- bracketed IPv6 addresses such as `[::1]` and `[::1]:8080`
- comma-separated values with surrounding whitespace

Bracketed `NO_PROXY` hosts are IPv6-only. Bracketed DNS names, `localhost`
and IPv4 addresses are rejected instead of being reinterpreted as normal host
rules.

Domain rules use strict label boundaries:

| Rule | Matches apex | Matches subdomains | Does not match |
|---|---:|---:|---|
| `example.com` | yes | yes | `badexample.com` |
| `.example.com` | yes | yes | `badexample.com` |
| `*.example.com` | yes | yes | `badexample.com` |

Invalid ports and malformed bracketed IPv6 rules are rejected when the client
configuration is created. FogHTTP rejects the whole environment configuration
instead of silently ignoring malformed `NO_PROXY` tokens. Empty comma-separated
tokens are ignored.

## TLS Environment Boundary

Explicit `tls=` always wins over `SSL_CERT_FILE`.

`SSL_CERT_FILE` is snapshotted when the client config is created. The
certificate file itself is read and validated later, when the Rust transport is
created.

FogHTTP intentionally does not expose a `verify=False` compatibility mode and
does not honor environment variables that disable certificate verification.
Use explicit `TLSConfig` for custom CA bundles and custom-only trust.
