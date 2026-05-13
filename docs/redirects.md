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
| `307` | `POST` is preserved; body is resent |
| `308` | `POST` is preserved; body is resent |

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
different origin by a redirect response.

When a redirect rewrites `POST` to `GET`, FogHTTP drops the request body and
strips body-specific headers:

- `Content-Encoding`
- `Content-Length`
- `Content-Type`
- `Transfer-Encoding`

For `307` and `308`, FogHTTP preserves the method and resends the current
buffered body. Future streaming bodies will use a stricter replay policy because
non-replayable streams must not be resent automatically.

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
