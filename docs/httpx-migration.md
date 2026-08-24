# Migrating from HTTPX

FogHTTP is not a drop-in replacement for HTTPX. The request shape is familiar,
but client ownership, defaults, timeout semantics, and several advanced features
are deliberately different. This guide reflects the current FogHTTP public API
and calls out the differences that commonly block a migration.

FogHTTP requires Python 3.11 or newer and a supported CPython wheel target.
Check the current [platform and ABI constraints](./limitations.md) before
changing the dependency, especially for free-threaded Python builds.

## Start With An Explicit Client

Production code should own and reuse one `Client` or `AsyncClient` at a clear
application lifecycle boundary. FogHTTP has no module-level `get()`, `post()`,
or hidden shared connection pool.

::: code-group

```python [HTTPX]
import httpx


response = httpx.get("https://api.example.com/users")
response.raise_for_status()
```

```python [FogHTTP]
import foghttp


with foghttp.Client() as client:
    response = client.get("https://api.example.com/users")
    response.raise_for_status()
```

:::

For a long-running service, create the client during application startup, pass
that explicit owner to the code that needs it, and close it during shutdown.
Create clients after a prefork server starts its worker process, and keep each
`AsyncClient` with one async owner and event loop. Do not create a new client
for every request. See
[Explicit client ownership](./lifecycle.md#explicit-client-ownership) for the
normative lifecycle and shutdown contract.

Unlike HTTPX, FogHTTP has no public setters for client defaults after creation.
Set `base_url`, authentication, redirect policy, and other defaults in the
constructor. Pass changing headers, params, and timeouts per request; for
example, rotate a bearer token through the request's `Authorization` header.
Use a request-aware auth callback or a separately configured client when the
client-wide policy itself must differ. Assigning an arbitrary attribute such as
`client.headers` does not reconfigure FogHTTP's request builder.

## Common Request And Response Replacements

Client-level `base_url`, `headers`, and `params`, plus per-request `headers`,
`params`, and `json`, have matching names. Their edge-case semantics are not
all identical.

::: code-group

```python [HTTPX]
import httpx


with httpx.Client(
    base_url="https://api.example.com/v1/",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
) as client:
    response = client.post(
        "users",
        params={"notify": "true"},
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
    payload = response.json()
    content_type = response.headers["content-type"]
```

```python [FogHTTP]
import foghttp


with foghttp.Client(
    base_url="https://api.example.com/v1/",
    headers={"accept": "application/json"},
    params={"api-version": "1"},
) as client:
    response = client.post(
        "users",
        params={"notify": "true"},
        json={"name": "Ada Lovelace"},
    )
    response.raise_for_status()
    payload = response.json()
    content_type = response.headers["content-type"]
```

:::

The async replacement keeps the same request arguments:

::: code-group

```python [HTTPX]
import asyncio

import httpx


async def main() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.example.com/users",
            params={"limit": 10},
        )
        response.raise_for_status()
        payload = response.json()


asyncio.run(main())
```

```python [FogHTTP]
import asyncio

import foghttp


async def main() -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(
            "https://api.example.com/users",
            params={"limit": 10},
        )
        response.raise_for_status()
        payload = response.json()


asyncio.run(main())
```

:::

Audit relative URLs before changing the import. HTTPX preserves the base path
for both `"users"` and `"/users"`. FogHTTP uses `"users"` for a path below
the base path, but treats `"/users"` as root-relative:

```python
import foghttp


with foghttp.Client(base_url="https://api.example.com/v1/") as client:
    below_base = client.build_request("GET", "users")
    from_root = client.build_request("GET", "/users")

assert below_base.url == "https://api.example.com/v1/users"
assert from_root.url == "https://api.example.com/users"
```

HTTPX request params replace a client default with the same key. Supplying any
non-empty client params, or supplying request `params=` even as `{}`, also
replaces a query string embedded in the request URL. FogHTTP instead preserves
all layers in order: URL query, client params, then request params. This can
change signatures, cache keys, and routing. Use one source of query parameters
when exact wire compatibility matters: remove the query from the URL and pass
only the final parameter set that HTTPX actually sent. Adding the old embedded
query to that set preserves its apparent intent, but is a deliberate wire-level
behavior change. Do not put overridable keys in FogHTTP client defaults.

Do not pass an `httpx.QueryParams` or `httpx.Headers` object directly when it
contains repeated keys. FogHTTP sees those foreign containers as mappings and
uses `.items()`, which collapses or combines repeats. Preserve the original
pairs with `params=old_params.multi_items()` or
`headers=old_headers.multi_items()`.

Normalize query and form values explicitly when wire spelling matters. For
example, HTTPX encodes Python `True` and `None` as `true` and an empty
value, while FogHTTP's current form/query encoder uses `True` and `None`.
Portable migration code should pass the intended strings.

HTTPX also accepts byte request headers and raw byte query strings. FogHTTP's
public contract requires string header names and values, and the raw-query form
is a string. Decode only byte forms known to be text whose UTF-8 wire form is
correct; `str(raw_bytes)` is not a decode. For an exact raw query, pass an
already percent-encoded ASCII string. FogHTTP has no byte-valued request-header
API, so keep HTTPX or use a protocol-defined ASCII representation when exact
non-ASCII header octets are part of the contract. FogHTTP exposes response
header octets as Latin-1-mapped strings. When an application genuinely needs
the original octets, recover them with `value.encode("latin-1")`.

Most buffered response access is also familiar, but several details are not
interchangeable:

| HTTPX | FogHTTP | Migration note |
|---|---|---|
| `response.content` | `response.content` | Both expose buffered bytes. |
| `response.text` | `response.text` | Both decode text; verify encoding behavior for unusual payloads. |
| `response.json()` | `response.json()` | FogHTTP decodes with `orjson` and accepts no decoder keyword arguments. |
| `response.headers[name]` | `response.headers[name]` | Both are case-insensitive. HTTPX combines repeated values for ordinary lookup; FogHTTP returns the last value. Use `get_list()` when repetition is possible. |
| `response.raise_for_status()` | `response.raise_for_status()` | FogHTTP raises only for `4xx` and `5xx`, and returns `None`; do not chain `.json()` from it. |
| `response.url` (`httpx.URL`) | `response.url` (`str`) | Remove unnecessary `str(...)`, or construct `foghttp.URL` when URL operations are needed. |
| `response.elapsed` (`timedelta`) | `response.elapsed` (`float`) | FogHTTP reports seconds directly. |

HTTPX supports client-level `default_encoding=` and a mutable
`response.encoding`. FogHTTP has neither override. For a buffered response that
requires a specific codec, use
`response.content.decode(codec, errors="replace")`; for streaming, pass
`encoding=` to `iter_text()` / `iter_lines()` or their async variants.

Audit exception handlers as well:

| HTTPX | FogHTTP | Migration note |
|---|---|---|
| `httpx.HTTPError` | `foghttp.FogHTTPError` | Base class for library errors. |
| `httpx.RequestError` | `foghttp.RequestError` | Request/transport failures; neither class includes status errors. |
| `httpx.HTTPStatusError` | `foghttp.HTTPStatusError` | FogHTTP stores `.response`, but has no `.request` shortcut. Its `.response` is typed as `object`; narrow it to the buffered or streaming response type before accessing `.request`. |
| `httpx.TimeoutException` | `foghttp.TimeoutError` | See the phase-specific timeout classes below. |
| No HTTPX safety-default equivalent | `foghttp.ResponseError` | Base class for status and buffered-response handling errors; it is not a `RequestError`. |

FogHTTP's default buffered-body limits can raise
`foghttp.ResponseBodyTooLargeError` or
`foghttp.ResponseBodyBudgetExceededError` before a buffered request returns a
`Response`. Catch the specific class, or catch `foghttp.ResponseError` /
`foghttp.FogHTTPError` at the intended boundary. Replacing an HTTPX
`RequestError` handler alone does not cover these failures.

FogHTTP request and timeout errors do not guarantee HTTPX's `.request`
attribute either. Preserve the URL or prepared request in caller context when
an error path needs it; timeout handlers can use `.origin` when diagnostics are
available.

FogHTTP's complete request merge rules, prepared-request behavior, and body
conflict matrix live in
[Request builder compatibility](./request-builder.md).

For custom JSON decoding, call the required parser directly, for example
`json.loads(response.content, parse_float=Decimal)`. Request `json=` also
uses `orjson`; when custom serialization is required, serialize explicitly
and pass the bytes through `content=` with an explicit
`Content-Type: application/json`.

Non-finite floats differ in both directions. HTTPX request JSON rejects
`NaN` and infinities, while FogHTTP serializes them as `null`. HTTPX response
JSON accepts non-standard `NaN`, while FogHTTP rejects it. Validate payloads
explicitly, or preserve HTTPX request behavior with stdlib `json.dumps`
configured with `ensure_ascii=False`, compact separators, and
`allow_nan=False`; encode the result as UTF-8 and pass it through `content=`.
Use the stdlib parser explicitly only when accepting a legacy non-standard
response is intentional.

FogHTTP rejects transport-managed request headers: `Host`, `Content-Length`,
`Transfer-Encoding`, `Trailer`, `TE`, `Connection`, `Upgrade`,
`Keep-Alive`, `Proxy-Connection`, and `Proxy-Authorization`. Leave routing
and framing to the transport, and put proxy credentials in `proxy=`. Keep
HTTPX when a custom `Host` or another manually controlled transport header is
part of the request contract.

## Client Defaults That Differ

Audit constructor defaults instead of copying an HTTPX client configuration
mechanically.

| Area | HTTPX | FogHTTP |
|---|---|---|
| Environment | `trust_env=True` by default | `trust_env=False` by default; opt in explicitly |
| Redirects | Disabled by default; can be overridden per request | Disabled by default; configured on the client |
| Timeouts | Five-second network-inactivity default | Explicit connect, pool, read, write, and total budgets |
| Protocols | HTTP/1.1, with optional HTTP/2 | HTTP/1.1 only |
| Other automatic request headers | Adds `Accept`, `Connection`, and `User-Agent` | Set required `Accept` and `User-Agent` values explicitly; leave `Connection` to the transport |
| Compression request header | Adds automatic `Accept-Encoding` negotiation | Does not add `Accept-Encoding`; buffered decoding works when the header is sent explicitly |
| Cookies | Client jar can be initialized with cookie values | Disabled by default; `cookies=True` enables a server-populated client jar |
| Buffered response size | No equivalent FogHTTP safety defaults | 10 MiB per response and 100 MiB aggregate by default |
| Limits | Connection-pool limits | Separate active-request, pending-request, connection, idle, and buffered-body limits |

Increase FogHTTP's `Limits.max_response_body_size` or
`Limits.max_buffered_response_bytes` deliberately when a trusted workload needs
larger buffered responses. Prefer streaming when the body should not be held in
memory.

FogHTTP automatic redirects currently cover `GET`, `HEAD`, `POST`, and
`QUERY`. A `PUT`, `PATCH`, or `DELETE` migration that depends on HTTPX
redirect behavior should keep HTTPX or handle each redirect explicitly after
validating destination, credentials, and body replayability.

## Authentication

Ordinary string Basic credentials move directly, but FogHTTP authentication is
client-level.

::: code-group

```python [HTTPX]
import httpx


with httpx.Client() as client:
    response = client.get(
        "https://api.example.com/me",
        auth=("service-user", "service-password"),
    )
```

```python [FogHTTP]
import foghttp


with foghttp.Client(
    auth=("service-user", "service-password"),
) as client:
    response = client.get("https://api.example.com/me")
```

:::

HTTPX also accepts byte credentials. FogHTTP requires a `(str, str)` pair,
encodes it as UTF-8, and rejects `:` in the username. Normalize legacy values
explicitly before migration. Keep HTTPX, or construct the exact `Authorization`
header deliberately, when an existing byte-level credential contract cannot be
represented by FogHTTP's Basic auth API.

For a per-request bearer token, pass an explicit `Authorization` header. For
client-wide refresh, FogHTTP accepts a synchronous request-aware auth callback.
It may run concurrently on transport worker threads, so it must be fast and
thread-safe, and it must not issue requests through the same client. Async auth
callbacks, Digest auth, OAuth flows, provider SDKs, and `.netrc` discovery are
not built in. Keep the provider flow outside FogHTTP, use the synchronous
callback when it fits, or retain HTTPX for an authentication contract that
requires its auth flow API. See [Authentication](./auth.md).

## Forms And Files

Non-empty mapping `data=` values use form-urlencoded encoding in both clients,
but scalar spelling can differ as described above. For repeated fields, a
mapping with list values works in both clients. FogHTTP also accepts a sequence
of pairs, while HTTPX 0.28.1 does not treat that shape as form data. Prefer
normalized strings for forms and `content=` for already encoded text or bytes.

Empty collections are not equivalent. HTTPX sends no body or form content type
for `data={}` or `files={}`; with non-empty `data` and empty `files`, it keeps
form-urlencoded encoding. FogHTTP encodes `data={}` as an empty form and treats
even `files={}` as multipart, including any accompanying form fields. Do not
pass an empty `files` collection conditionally. Choose no body, an empty form,
or multipart explicitly at the call site.

::: code-group

```python [HTTPX]
response = client.post(
    "https://api.example.com/token",
    data={"grant_type": "client_credentials", "scope": "read"},
)
```

```python [FogHTTP]
response = client.post(
    "https://api.example.com/token",
    data={"grant_type": "client_credentials", "scope": "read"},
)
```

:::

Multipart tuples also keep the familiar `(filename, content, content_type)`
shape:

::: code-group

```python [HTTPX]
with open("report.csv", "rb") as report:
    response = client.post(
        "https://api.example.com/reports",
        data={"kind": "monthly"},
        files={"report": ("report.csv", report, "text/csv")},
    )
```

```python [FogHTTP]
with open("report.csv", "rb") as report:
    response = client.post(
        "https://api.example.com/reports",
        data={"kind": "monthly"},
        files={"report": ("report.csv", report, "text/csv")},
    )
```

:::

HTTPX rewinds a seekable multipart file to offset zero before reading it;
FogHTTP starts at the file's current position. Call `seek(0)` immediately before
the request when the whole file must be sent, or use a factory that opens a
fresh file for each attempt.

With FogHTTP, direct file objects passed through `files=` remain caller-owned;
the surrounding `with` block closes them. A direct file or stream passed as the
whole `content=` body becomes FogHTTP-owned only when a validated request is
handed to the transport. FogHTTP then invokes `close()` or `aclose()` under a
best-effort contract: cleanup errors are suppressed, and bounded async cleanup
may continue after the request returns. Before transport handoff, including an
unsent prepared request or a stream context that was never entered, the caller
must close it. Use a zero-argument stream factory when a redirect or retry must
obtain a fresh replayable body.

Factory-backed multipart parts may be combined with buffered bytes-like parts,
but not with direct file or stream parts. Make every non-buffered part
factory-backed when the whole multipart body must be replayable; otherwise keep
the direct parts caller-owned and accept that the body is non-replayable.

FogHTTP multipart values support direct content, `(filename, content)`, and
`(filename, content, content_type)`. HTTPX infers a media type from `filename`
for the two-element form; FogHTTP uses `application/octet-stream`. Use the
three-element form when the server-visible media type matters. Encode HTTPX
string part content to bytes before passing it to FogHTTP. HTTPX four-tuples
with per-part headers, `filename=None` forms, and a `None` part content type are
not supported. Use `data=` for ordinary form fields, choose a supported explicit
content type, or keep HTTPX when omitted/custom part headers are required.
Remove a caller-made multipart `boundary` and let FogHTTP generate it. Multipart
field names, filenames, and part content types are currently printable ASCII
only. See [Upload typing contracts](./upload-types.md).

## Cookies

FogHTTP does not accept a cookie mapping or expose a mutable public cookie jar.
Enable its bounded, in-memory jar and let responses populate it:

```python
import foghttp


with foghttp.Client(cookies=True) as client:
    login = client.post(
        "https://api.example.com/login",
        json={"username": "ada", "password": "service-password"},  # pragma: allowlist secret
    )
    login.raise_for_status()

    profile = client.get("https://api.example.com/profile")
    profile.raise_for_status()
```

For one fixed request cookie, pass an explicit `Cookie` header. If migration
requires preloading, mutating, inspecting, persisting, or sharing a jar, keep
that workflow in HTTPX or redesign it around a server-issued session. FogHTTP's
jar intentionally does not provide browser public-suffix, SameSite,
partitioned, or third-party-cookie policy. See [Cookies](./cookies.md).

## Proxies

A single HTTP proxy endpoint has a direct client-level replacement:

::: code-group

```python [HTTPX]
import httpx


with httpx.Client(proxy="http://proxy.internal:8080") as client:
    response = client.get("https://api.example.com/health")
```

```python [FogHTTP]
import foghttp


with foghttp.Client(proxy="http://proxy.internal:8080") as client:
    response = client.get("https://api.example.com/health")
```

:::

FogHTTP's proxy endpoint must use `http://`; HTTPS targets are tunnelled through
it with `CONNECT`. To use `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`,
or `SSL_CERT_FILE`, set `trust_env=True` explicitly. Environment values are
snapshotted when the client is created.

Audit `NO_PROXY` syntax before enabling it. FogHTTP supports `*`, exact and
suffix hosts, `localhost`, IP literals, and optional ports. It rejects CIDR
rules such as `10.0.0.0/8`; keep routing at the network layer or retain a client
that supports the required rule form.

TLS environment behavior is not equivalent. HTTPX uses `SSL_CERT_FILE` or
`SSL_CERT_DIR` as a replacement trust location. FogHTTP ignores `SSL_CERT_DIR`,
while its environment-derived `SSL_CERT_FILE` is added to bundled WebPKI roots.
When the file must be the only trust root, pass it through
`foghttp.TLSConfig(ca_certificates=(ca_file,), trust_webpki_roots=False)`, where
`ca_file` is a `pathlib.Path`. Convert a CA directory to explicit PEM files or a
combined PEM bundle, or keep HTTPX when directory trust semantics are required.
See [TLS trust](./tls.md).

There is no per-request proxy, SOCKS support, TLS-to-proxy endpoint, PAC/WPAD,
or HTTPX-style mount routing. Use separate explicitly owned clients for a small
fixed set of proxy policies, move routing to a trusted network boundary, or keep
HTTPX when dynamic mounts or SOCKS are required. Cross-origin redirects
currently fail closed when the request uses environment-derived proxy policy;
merely loading `SSL_CERT_FILE` through `trust_env=True` does not create that
proxy condition. See [Proxy and trust_env](./proxies.md).

## Streaming

Both libraries use context-managed response streaming. Their byte iterators
have different content-decoding semantics, so request an identity-encoded
response when applying this direct replacement:

::: code-group

```python [HTTPX]
import httpx


with httpx.Client() as client:
    with client.stream(
        "GET",
        "https://api.example.com/events",
        headers={"Accept-Encoding": "identity"},
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            process(chunk)
```

```python [FogHTTP]
import foghttp


with foghttp.Client() as client:
    with client.stream(
        "GET",
        "https://api.example.com/events",
        headers={"Accept-Encoding": "identity"},
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            process(chunk)
```

:::

`AsyncClient.stream()` is also an async context manager and exposes
`aiter_bytes()`, `aiter_text()`, and `aiter_lines()`. HTTPX `iter_bytes()`
and `aiter_bytes()` decode supported content encodings; FogHTTP byte, text,
and line iterators do not. FogHTTP `iter_bytes()` / `aiter_bytes()` are
therefore closest to HTTPX `iter_raw()` / `aiter_raw()`: they expose bytes
after HTTP transfer framing but before content-encoding decompression.

HTTPX byte, text, and raw iterators accept `chunk_size`; FogHTTP iterators do
not. Remove that argument or rechunk in application code when fixed-size output
is part of the consumer contract. FogHTTP `iter_lines()` / `aiter_lines()` also
limit a line to 1,048,576 decoded characters by default. Choose
`max_line_chars` deliberately; use `None` only for trusted streams where
unbounded line buffering is acceptable.
For streaming responses, HTTPX finalizes `elapsed` after the body is consumed or
closed, while FogHTTP's `elapsed` is available after headers and excludes later
body consumption. Measure wall-clock time around the whole stream context when
end-to-end download latency is required.

FogHTTP has no top-level `stream()`, separately named raw iterator,
`read()` / `aread()`, or download progress property. Request
`Accept-Encoding: identity`, decompress in an application pipeline, or use the
buffered API for transparent `gzip`, `deflate`, and `br` decoding. Use a
normal buffered request when the whole response must be loaded, and count
yielded bytes in application code for progress. See
[Response streaming](./streaming.md).

## Timeout Semantics

An HTTPX scalar timeout has no exact FogHTTP equivalent. FogHTTP accepts
`None` only as the constructor/request sentinel for configured defaults; it
does not disable timeouts. Build a `Timeouts` value with finite non-negative
seconds and choose its transport-phase deadline independently:

::: code-group

```python [HTTPX]
import httpx


timeout = httpx.Timeout(10.0, connect=2.0)
with httpx.Client(timeout=timeout) as client:
    response = client.get("https://api.example.com/health")
```

```python [FogHTTP]
import foghttp


timeouts = foghttp.Timeouts(
    connect=2.0,
    pool=10.0,
    read=10.0,
    write=10.0,
    total=60.0,  # Transport-phase deadline, not an HTTPX scalar equivalent.
)
with foghttp.Client(timeouts=timeouts) as client:
    response = client.get("https://api.example.com/health")
```

:::

The meanings are not identical:

- `connect` configures the connector when the client's lazy transport is
  created; a per-request `Timeouts.connect` value does not reconfigure it.
- `pool` covers FogHTTP request-slot and enabled connection-limit acquisition.
- `read` and `write` are progress timeouts for response and request bodies.
- `total` is one broader deadline shared across acquire, request send, response
  headers, buffered body collection, redirect hops, and retry attempts. For a
  streamed response it ends after headers; it does not bound later consumption.
- FogHTTP has no timeout-disabled `None` mode. Passing `None` selects the
  client default or FogHTTP's finite defaults.
- A request-level `Timeouts` object replaces the complete client-level object;
  its omitted fields use `Timeouts` class defaults, not client values. Specify
  every field whose value matters. Its `connect` value still cannot reconfigure
  the client connector.

Use an outer application deadline when work beyond FogHTTP's transport phase
must be bounded, including stream consumption or a running auth callback. For
async code, `asyncio.timeout()` can bound the caller's wait, but it does not
preempt a synchronous auth callback that is already running. When that outer
deadline expires, it raises the built-in `TimeoutError` outside the context,
not `foghttp.TimeoutError`; handle the application and transport deadlines
separately.

Catch `foghttp.PoolTimeout`, `foghttp.ReadTimeout`, and
`foghttp.WriteTimeout` before the base `foghttp.TimeoutError`. Connector
failures do not yet have stable dedicated `ConnectTimeout` mapping and may
surface as `NetworkError`; do not translate an HTTPX `ConnectTimeout` handler
mechanically. See [Timeout model](./timeouts.md).

## Unsupported Or Non-Equivalent HTTPX Features

| HTTPX capability | FogHTTP status | Migration choice |
|---|---|---|
| Module-level request helpers | Not provided | Own and reuse an explicit client; use a short-lived client only for genuinely one-off code. |
| `client.options()` shortcut | Not provided | Use `client.request("OPTIONS", url)`; FogHTTP does not automatically follow redirects for `OPTIONS`. |
| HTTP/2 | Not provided | Keep HTTPX when HTTP/2 or multiplexing is a requirement. |
| Request-level auth, cookies, proxy, or redirect policy | Not provided as equivalent options | Split workloads across explicitly configured clients, or supply an explicit request header where that is safe. |
| Digest auth, async auth flows, OAuth/provider integrations, `.netrc` | Not built in | Resolve credentials outside FogHTTP, use Basic or a synchronous auth hook, or keep HTTPX. |
| Preloaded, mutable, inspectable, or persistent cookie jars | Not provided | Use a server-populated `cookies=True` session, an explicit `Cookie` header, or keep HTTPX/browser tooling. |
| SOCKS, proxy mounts, per-route proxy policy, TLS-to-proxy | Not provided | Use separate clients or network-layer routing; keep HTTPX for dynamic routing. |
| Custom transports, `MockTransport`, WSGI/ASGI in-process transports | Not public extension points | Test against a local loopback server or keep HTTPX for in-process transport tests. |
| `verify=False`, arbitrary `SSLContext`, client certificates | Not provided | Use `TLSConfig` with explicit CA files; keep HTTPX when mTLS or another TLS mode is required. |
| Content-decoded response-byte streaming | Not provided | Request an uncompressed stream, decompress FogHTTP's encoded bytes in application code, use buffered decoding, or keep HTTPX. |
| HTTPX event-hook API | Not a drop-in contract | Use FogHTTP telemetry for observation, policy hooks for admission/response-head policy, auth hooks for credentials, or an application wrapper. |

FogHTTP also has no automatic `Accept-Encoding` negotiation, operating-system
trust-store loading, browser-grade cookie policy, or per-request connector
reconfiguration. Review the current [Limitations](./limitations.md) before
removing HTTPX from a service dependency set.

## Migration Checklist

- Replace module-level calls with an explicitly owned sync or async client.
- Compare constructor defaults, especially environment, limits, compression,
  response-size budgets, redirects, and timeouts.
- Move request-level auth, cookie, proxy, and redirect configuration to an
  appropriate client boundary.
- Exercise form, multipart, streaming, redirect, and timeout failure paths with
  production-shaped inputs.
- Verify exception handlers against FogHTTP's error hierarchy and status rules.
- Keep HTTPX for any unsupported feature that is part of the application
  contract; do not emulate transport or security features with ad hoc wrappers.
