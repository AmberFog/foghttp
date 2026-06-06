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

## Security Policy

FogHTTP applies a conservative redirect security policy on every redirect hop.

For same-origin redirects, request headers are preserved unless the redirect
changes the request method and drops the body.

For cross-origin redirects, FogHTTP strips sensitive headers before sending the
next request:

- `Authorization`
- `Proxy-Authorization`
- `Cookie`
- `Origin`
- `Referer`

This is intentionally strict. It prevents credentials, manually supplied
cookies, origin metadata, and referrer metadata from being forwarded to a
different origin by a redirect response. `Host` is transport-managed and cannot
be set manually through the safe API.

When a redirect rewrites `POST` to `GET`, FogHTTP drops the request body and
strips body-specific headers:

- `Content-Encoding`
- `Content-Length`
- `Content-Type`
- `Transfer-Encoding`

`Content-Length` and `Transfer-Encoding` are transport-managed and cannot be set
manually through the safe API.

For same-origin `307` and `308`, FogHTTP preserves the method and resends the
current buffered body. For cross-origin `307` and `308`, FogHTTP preserves the
method but drops the body and body-specific headers before the next request.
This prevents JSON payloads, tokens, form data, and other request bodies from
being forwarded to a different origin by a redirect response.

FogHTTP also blocks `https -> http` redirects. Scheme downgrade redirects are
too easy to misuse once credentials, cookies, body replay, or future auth helpers
are involved, so the safe default is to fail the request instead of silently
following the downgrade.

Future streaming bodies will use an explicit replayability model because
non-replayable streams must not be resent automatically.

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
`RequestError`.

```python
with foghttp.Client(follow_redirects=True, max_redirects=5) as client:
    response = client.get("https://example.com/redirect-loop")
```

## Current Limitations

FogHTTP does not yet implement cookie jar behavior. User-supplied `Cookie`
headers are treated as sensitive and are not forwarded across origins during
redirects.
