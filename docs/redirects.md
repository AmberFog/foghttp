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

## Redirect Limit

`max_redirects` defaults to `20`. If the limit is exceeded, FogHTTP raises
`RequestError`.

```python
with foghttp.Client(follow_redirects=True, max_redirects=5) as client:
    response = client.get("https://example.com/redirect-loop")
```

## Current Limitations

FogHTTP does not yet implement auth stripping, cookie jar behavior, or
cross-origin redirect policy. Those rules are planned and the redirect code is
structured so they can be added without rewriting the transport loop.
