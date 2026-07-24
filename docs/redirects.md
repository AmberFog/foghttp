# Redirects

Redirects are disabled by default. Enable them on the client with
`follow_redirects=True`.

::: code-group

```python [Async]
import foghttp


async with foghttp.AsyncClient(
    follow_redirects=True,
    max_redirects=20,
) as client:
    response = await client.get("https://example.com/old")

print(response.url)
print(response.history)
```

```python [Sync]
import foghttp


with foghttp.Client(
    follow_redirects=True,
    max_redirects=20,
) as client:
    response = client.get("https://example.com/old")

print(response.url)
print(response.history)
```

:::

## Supported Status Codes

- `301 Moved Permanently`
- `302 Found`
- `303 See Other`
- `307 Temporary Redirect`
- `308 Permanent Redirect`

## Final URL and History

`response.url` contains the final URL. `response.history` contains intermediate
responses in redirect order.

```python
print(response.url)

for item in response.history:
    print(item.status_code, item.url)
```

Every response also includes request metadata:

```python
print(response.request.method)
print(response.request.url)

for item in response.history:
    print(item.request.method, item.request.url)
```

## POST Method Rules

FogHTTP follows common browser-compatible POST redirect behavior:

| Status | Method behavior |
|---|---|
| `301` | `POST` becomes `GET`; body is dropped |
| `302` | `POST` becomes `GET`; body is dropped |
| `303` | `POST` becomes `GET`; body is dropped |
| `307` | `POST` is preserved only for same-origin redirects; cross-origin body replay is dropped |
| `308` | `POST` is preserved only for same-origin redirects; cross-origin body replay is dropped |

::: code-group

```python [Async]
async with foghttp.AsyncClient(follow_redirects=True) as client:
    response = await client.post(
        "https://example.com/submit",
        json={"name": "Ada"},
    )

print(response.request.method)
```

```python [Sync]
with foghttp.Client(follow_redirects=True) as client:
    response = client.post(
        "https://example.com/submit",
        json={"name": "Ada"},
    )

print(response.request.method)
```

:::

## QUERY Method Rules

FogHTTP follows the redirect semantics for `QUERY` defined by
[RFC 10008](https://www.rfc-editor.org/rfc/rfc10008.html):

| Status | Method behavior |
|---|---|
| `301` | `QUERY` and a replayable body are preserved for same-origin redirects |
| `302` | `QUERY` and a replayable body are preserved for same-origin redirects |
| `303` | `QUERY` becomes `GET`; body and body-specific headers are dropped |
| `307` | `QUERY` and a replayable body are preserved for same-origin redirects |
| `308` | `QUERY` and a replayable body are preserved for same-origin redirects |

Unlike POST, QUERY does not become GET after `301` or `302`. Direct streams and
other non-replayable bodies fail closed when a same-origin redirect would need
to resend the query content. Factory-backed streams remain replayable because
FogHTTP can request a fresh provider for each attempt.

For cross-origin `301`, `302`, `307`, and `308`, FogHTTP preserves the QUERY
method but does not forward the request content, sensitive headers, or
body-specific headers to the new origin. A destination that requires a query
body and `Content-Type` can therefore reject that sanitized request. This is a
deliberate data-boundary rule rather than an attempt to recreate the original
query at a different origin.

## Security Policy

FogHTTP applies a conservative redirect security policy on every redirect hop.
The policy runs after the target URL and body action have been resolved and
before the next request is sent.

| Header category | Fields | Redirect behavior |
|---|---|---|
| Transport routing, framing, proxy, and connection | `Host`, `Content-Length`, `Transfer-Encoding`, `Connection`, `Keep-Alive`, `Proxy-Authorization`, `Proxy-Connection`, `TE`, `Trailer`, `Upgrade`, plus fields named by `Connection` | Always removed from the previous request. The transport derives fresh routing and framing fields for the new URL and body and applies proxy credentials for the selected route. |
| Conditional validators | `If-Match`, `If-None-Match`, `If-Modified-Since`, `If-Unmodified-Since`, `If-Range` | Always removed because the validator describes the previous target resource. |
| Origin-scoped credentials and metadata | `Authorization`, `Cookie`, `Origin`, `Referer` | Preserved for same-origin redirects and removed for cross-origin redirects. |
| Callable auth output | Every header name actually applied from `auth=` during the logical request | Refreshed on same-origin redirects. Removed on the first cross-origin redirect, after which auth remains disabled for that logical request. Caller-owned values that prevented an auth update remain governed by the normal redirect matrix. |
| Content metadata | Every `Content-*` field, including `Content-Type`, `Content-Encoding`, `Content-Language`, `Content-Location`, `Content-Range`, `Content-Disposition`, and `Content-Digest`; also legacy `Digest`, current `Repr-Digest`, and `Last-Modified` | Preserved only while the request body is preserved. Removed when a method rewrite or cross-origin policy drops the body. |
| Other caller headers | For example, `Accept` and application-specific fields | Preserved. |

Same-origin means that the scheme, normalized host, and effective port all
match. A change to any of those components is cross-origin.

The safe API already rejects manual transport-managed fields. Rebuilding them
inside the Rust redirect policy also protects the lower-level boundary and
prevents stale authority, framing, proxy credentials, or connection state from
crossing a hop.

The conditional and content rules follow the redirect guidance in
[RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html). FogHTTP recognizes both
the obsolete `Digest` field and its current
[RFC 9530](https://www.rfc-editor.org/rfc/rfc9530.html) replacements.

For same-origin method-preserving redirects, FogHTTP resends a replayable body.
For cross-origin method-preserving redirects, FogHTTP preserves the method but
drops any body and its content metadata before the next request. This rule also
protects bodies supplied through the generic `request()` API for methods whose
convenience helpers do not accept body arguments. It prevents JSON payloads,
tokens, form data, and other request bodies from being forwarded to a different
origin by a redirect response.

FogHTTP also blocks `https -> http` redirects. Scheme downgrade redirects are
too easy to misuse once credentials, cookies, body replay, or auth hooks
are involved, so the safe default is to fail the request instead of silently
following the downgrade.

Direct streaming bodies use the explicit non-replayable path and are not resent
automatically. Factory-backed streams are replayable because each attempt gets
a fresh provider.

Automatic redirects cannot infer whether an arbitrary application header such
as `X-API-Key` contains an origin-scoped secret. Keep automatic redirects
disabled and follow the response explicitly when custom credentials require a
different forwarding policy. This is also the explicit escape hatch for callers
that need behavior looser than the built-in matrix.

## Proxy Policy

Redirects interact with proxy routing because a redirect target can change the
proxy decision.

With explicit `proxy=`, FogHTTP treats the proxy as a stable client-level
policy. HTTP redirects to another `http://` origin continue through the same
proxy. Redirects to `https://` upgrade to a `CONNECT` tunnel through the same
proxy.

With `trust_env=True`, proxy decisions depend on the target URL, `NO_PROXY`,
scheme-specific proxy variables, and `ALL_PROXY`. This foundation release does
not yet recompute trusted-environment proxy decisions for each redirect hop
inside Rust. Same-origin redirects can continue, but cross-origin redirects
under environment proxy policy fail closed instead of reusing the initial
proxy/direct decision. This strict rule also applies when both HTTP origins
would likely use the same configured proxy; per-hop environment proxy
recomputation is planned separately.

## Redirect Limit

`max_redirects` defaults to `20`. If the limit is exceeded, FogHTTP raises
`RequestError`. The diagnostic identifies the normalized origin but omits URL
userinfo, path, query parameters, and fragments.

```python
with foghttp.Client(follow_redirects=True, max_redirects=5) as client:
    response = client.get("https://example.com/redirect-loop")
```

## Cookie Scope

With `cookies=True`, FogHTTP removes its managed `Cookie` header before every
redirect and selects again for the target URL. Host/domain, path, expiry, and
`Secure` rules therefore decide what the next hop receives; a source cookie is
never blindly copied to another host. Cookie scope does not include the TCP
port, matching HTTP cookie semantics.

A caller-supplied `Cookie` remains authoritative on same-origin redirects and
is stripped by the normal cross-origin header policy. After that stripping, a
cookie matching the redirect target may be selected from the managed jar. See
[Cookies](./cookies.md) for the complete contract.
