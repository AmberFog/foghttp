# Proxy and trust_env

FogHTTP supports plain HTTP proxy routing for `http://` target URLs.

`https://` target URLs over proxy require HTTP `CONNECT`; that is intentionally
out of scope for the current proxy foundation and is tracked separately.

## Explicit Proxy

Use client-level `proxy=` when all plain HTTP requests from that client should
use the same proxy endpoint:

```python
import foghttp

with foghttp.Client(proxy="http://proxy.internal:8080") as client:
    response = client.get("http://api.internal/items")

print(response.status_code)
```

The same option is available on `AsyncClient`.

FogHTTP sends proxied HTTP requests in absolute-form:

```http
GET http://api.internal/items HTTP/1.1
Host: api.internal
```

The `Host` header remains the target origin host. It is not replaced with the
proxy host.

## Proxy Authentication

Proxy credentials can be passed as userinfo in the proxy URL:

```python
username = load_proxy_username()
password = load_proxy_password()
proxy = f"http://{username}:{password}@proxy.internal:8080"

with foghttp.Client(proxy=proxy) as client:
    response = client.get("http://api.internal/items")
```

FogHTTP keeps the canonical proxy endpoint without userinfo and sends
`Proxy-Authorization` as a transport-managed header only when the request uses
the proxy path. The header is not part of `Request.headers`, response history,
or user-facing request metadata.

Manual `Proxy-Authorization` headers are rejected by the safe public API.

Proxy credentials are redacted in debug-facing representations and should not
be logged directly.

## trust_env

`trust_env=False` remains the default.

With `trust_env=True`, FogHTTP snapshots supported environment variables when
the client is created:

| Variable | Current behavior |
|---|---|
| `HTTP_PROXY` / `http_proxy` | Routes plain HTTP target URLs through the selected proxy. Uppercase `HTTP_PROXY` is ignored when `REQUEST_METHOD` is set to avoid HTTPoxy-style CGI leakage. |
| `HTTPS_PROXY` / `https_proxy` | Parsed and validated for future HTTPS `CONNECT` support. It does not route `https://` targets yet. |
| `ALL_PROXY` / `all_proxy` | Fallback proxy when no scheme-specific proxy is set. For this release it can route plain HTTP targets. |
| `NO_PROXY` / `no_proxy` | Bypass rules for environment-derived proxy decisions. Explicit `proxy=` wins over `NO_PROXY`. |
| `SSL_CERT_FILE` / `ssl_cert_file` | Converted to `TLSConfig(ca_certificates=(...))` if `tls=` is not passed explicitly. |
| `SSL_CERT_DIR` | Ignored. Directory trust-store loading is not implemented. |

Lowercase proxy variables win over uppercase variants for the same setting.
Scheme-specific proxy variables win over `ALL_PROXY`.

Environment variables are not read on every request.

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

## Not Implemented Yet

- HTTPS proxy `CONNECT` for `https://` targets
- SOCKS5/SOCKS5h
- PAC/WPAD or platform/browser proxy discovery
- per-route proxy policies
- proxy retry policy
