# Proxy and trust_env

FogHTTP supports plain HTTP proxy routing for `http://` target URLs and HTTPS
proxy tunnelling for `https://` target URLs via HTTP `CONNECT`.

For `https://` targets, FogHTTP opens a `CONNECT` tunnel to the proxy and then
performs the TLS handshake against the **target** host over that tunnel, so the
certificate is validated for the target origin, not the proxy. If the tunnel
cannot be established — proxy authentication failure, a non-2xx `CONNECT`
status, or the proxy closing the tunnel early — FogHTTP raises `NetworkError`
(a `RequestError` subtype) instead of silently falling back to a direct
connection.

## Explicit Proxy

Use client-level `proxy=` when all requests from that client should use the
same HTTP proxy endpoint. Both `http://` and `https://` targets are routed
through the proxy: plain HTTP uses absolute-form, HTTPS is tunnelled via
`CONNECT`:

```python
import foghttp

with foghttp.Client(proxy="http://proxy.internal:8080") as client:
    plain = client.get("http://api.internal/items")
    secure = client.get("https://api.internal/items")  # tunnelled via CONNECT

print(plain.status_code, secure.status_code)
```

The same option is available on `AsyncClient`.

Proxy endpoint URLs must currently use the `http://` scheme. HTTPS target URLs
are still supported through that proxy via `CONNECT`, but TLS-to-proxy
endpoints such as `https://proxy.internal:443` are not implemented yet and are
rejected when client configuration is created.

An empty endpoint path and `/` are treated as the same proxy endpoint. Paths,
queries, and fragments other than `/` are rejected.

FogHTTP sends proxied HTTP requests in absolute-form:

```http
GET http://api.internal/items HTTP/1.1
Host: api.internal
```

The `Host` header remains the target origin host. It is not replaced with the
proxy host.

## HTTPS CONNECT Tunnelling

For `https://` targets, FogHTTP sends a `CONNECT target-host:port` request to
the proxy and, once the proxy answers `200`, performs the TLS handshake through
the tunnel:

```http
CONNECT api.internal:443 HTTP/1.1
Host: api.internal:443
```

TLS is validated against the **target** host using the same `TLSConfig` rules as
a direct connection; the proxy never terminates TLS and cannot impersonate the
target. A failed tunnel (`CONNECT` non-2xx, proxy auth failure, or early close)
maps to a stable `NetworkError`, releases the request slot, and does not return
a poisoned connection to the pool. The tunnelled request itself is sent in
origin-form, exactly like a direct HTTPS request.

Connection limits, pool telemetry, and socket telemetry for HTTPS CONNECT are
keyed by the target origin whose TLS session is tunnelled. They do not change
meaning when a proxy is configured. Use the separate proxy endpoint diagnostics
described below when the question is about the proxy hop itself.

`Timeouts.connect` bounds the whole connect phase, including the `CONNECT`
handshake, so a proxy that accepts the socket but never answers `CONNECT` fails
with a connect timeout instead of hanging until the total deadline. This uses
the client-level connector timeout; per-request `timeout.connect` does not
reconfigure the connector yet. Request cancellation during tunnel setup aborts
the attempt and releases the slot.

## Proxy Endpoint Diagnostics

`client.dump_proxy_diagnostics()` reports a Rust-owned diagnostic snapshot of
physical proxy connections and HTTPS `CONNECT` tunnels, grouped by canonical
proxy endpoint:

```python
diagnostics = client.dump_proxy_diagnostics()
proxy = diagnostics["endpoints"].get("http://proxy.internal:8080")
if proxy is not None:
    print(proxy["active_connections"], proxy["active_tunnels"])
```

The endpoint key contains only `scheme://host:port`. It never contains proxy
credentials, target path/query data, request or response headers, or body data.
Explicit `proxy=` and `trust_env=True` use the same diagnostics path. A client
with separate HTTP and HTTPS proxies has at most those two configured endpoint
keys; when both schemes use one endpoint, their counters are combined.

| field | meaning |
| --- | --- |
| `connection_attempts` | Physical connection attempts to the proxy endpoint, including failed or cancelled attempts. |
| `connections_opened`, `connections_open_failed`, `connections_closed` | Successful opens, failed/cancelled opens, and tracked connection drops. |
| `active_connections` | Currently tracked physical connections to the proxy. |
| `tunnel_attempts`, `tunnels_established`, `tunnel_failures` | HTTPS `CONNECT` attempts and terminal outcomes after a physical proxy connection opens. |
| `tunnel_auth_failures`, `tunnel_timeouts`, `tunnel_early_closes` | Subsets of tunnel failures for HTTP 407, timeout, and proxy close before a complete CONNECT response. |
| `active_tunnels` | Established CONNECT tunnels whose physical proxy connection is still tracked. |
| `last_activity_at_ns` | Monotonic time of the latest endpoint counter change, relative to the current Rust metrics lifetime. |

`dump_proxy_diagnostics()` is intentionally separate from `TransportStats` and
`dump_transport_state()["origins"]`: those APIs continue to describe logical
target origins and target-keyed capacity. Proxy diagnostics are an on-demand,
eventually coherent incident view, not an SLA-grade exporter source. Direct
clients create no proxy endpoint metrics, and direct requests perform no proxy
counter updates.

FogHTTP creates the Rust transport lazily. Before the first transport request,
the method returns a synthetic snapshot with `snapshot_sequence == 0` and an
empty `endpoints` mapping. Once the configured proxy transport exists, endpoint
entries may be present with zero counters until that route is used.

## Proxy Authentication

Proxy credentials can be passed as userinfo in the proxy URL:

```python
username = load_proxy_username()
password = load_proxy_password()
proxy = f"http://{username}:{password}@proxy.internal:8080"

with foghttp.Client(proxy=proxy) as client:
    response = client.get("http://api.internal/items")
```

FogHTTP keeps the canonical proxy endpoint without userinfo and manages
`Proxy-Authorization` as a transport-owned credential. For plain HTTP proxying
it is sent as an absolute-form request header; for HTTPS it is sent only on the
`CONNECT` request to the proxy and never on the tunnelled request to the target
origin. In both cases the header is not part of `Request.headers`, response
history, or user-facing request metadata.

Manual `Proxy-Authorization` headers are rejected by the safe public API.

Proxy credentials are redacted in debug-facing representations and should not
be logged directly.

## trust_env

`trust_env=False` remains the default.

With `trust_env=True`, FogHTTP snapshots supported environment variables when
the client is created:

| Variable | Current behavior |
|---|---|
| `HTTP_PROXY` / `http_proxy` | Routes plain HTTP target URLs through the selected HTTP proxy endpoint. Uppercase `HTTP_PROXY` is ignored when `REQUEST_METHOD` is set to avoid HTTPoxy-style CGI leakage. |
| `HTTPS_PROXY` / `https_proxy` | Tunnels `https://` target URLs through the selected HTTP proxy endpoint via `CONNECT`. |
| `ALL_PROXY` / `all_proxy` | Fallback proxy when no scheme-specific proxy is set. Routes plain HTTP targets and tunnels `https://` targets via `CONNECT`. |
| `NO_PROXY` / `no_proxy` | Bypass rules for environment-derived proxy decisions. Explicit `proxy=` wins over `NO_PROXY`. |
| `SSL_CERT_FILE` / `ssl_cert_file` | Converted to `TLSConfig(ca_certificates=(...))` if `tls=` is not passed explicitly. |
| `SSL_CERT_DIR` | Ignored. Directory trust-store loading is not implemented. |

Lowercase proxy variables win over uppercase variants for the same setting.
Scheme-specific proxy variables win over `ALL_PROXY`.

HTTP and HTTPS proxies are routed independently: plain-HTTP targets use the
HTTP-scheme proxy (`HTTP_PROXY`/`ALL_PROXY`) in absolute-form, and HTTPS targets
use the HTTPS-scheme proxy (`HTTPS_PROXY`/`ALL_PROXY`) via `CONNECT`. They may
point at the same or at different HTTP proxy endpoints. The proxy endpoint URL
itself must still use `http://`.

Environment variables are not read on every request.

## Redirects With Proxy Policy

Explicit `proxy=` is a stable client-level policy. HTTP redirects from one
`http://` origin to another `http://` origin continue through the same proxy,
and a redirect from a proxied `http://` request to an `https://` target upgrades
to a `CONNECT` tunnel through the same proxy.

Environment-derived proxy routing can change on each URL because `NO_PROXY`,
scheme-specific proxy variables and `ALL_PROXY` are evaluated against the
target origin. Rust follows redirects internally, and this foundation release
does not yet recompute trusted-environment proxy decisions per redirect hop.
For that reason, same-origin redirects can continue, but cross-origin redirects
under environment proxy policy fail closed instead of reusing the initial proxy
decision. This includes `http://` to `http://` cross-origin redirects that
would likely use the same configured proxy; per-hop environment proxy
recomputation is planned separately.

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

CIDR rules such as `10.0.0.0/8` are not supported yet and are rejected instead
of being silently treated as hostname rules.

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

## SSRF Policy Compatibility

Requests that select a proxy route fail closed when `SSRFPolicy` is enabled.
Forward and `CONNECT` proxies can resolve the target hostname remotely, so the
client cannot guarantee that its locally checked DNS result is the address
used by the proxy. See [SSRF protection](./ssrf.md) for the trust boundary and
recommended network-layer controls.

## Not Implemented Yet

- SOCKS5/SOCKS5h
- TLS-to-proxy endpoints (`https://proxy.example:443`)
- PAC/WPAD or platform/browser proxy discovery
- per-route proxy policies
- proxy failover, rotation, or per-route policy
