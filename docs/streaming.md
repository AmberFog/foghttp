# Async Streaming

FogHTTP supports an async bytes-first response streaming API through
`AsyncClient.stream()`.

Use it when the response body should be consumed incrementally instead of being
fully buffered into `Response.content`.

```python
import asyncio

import foghttp
from foghttp.methods import GET


async def main() -> None:
    async with foghttp.AsyncClient() as client:
        async with client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response:
            response.raise_for_status()

            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)

            print(response.status_code, total)


asyncio.run(main())
```

## Contract

`client.stream()` returns an async context manager. The request is sent when the
context is entered, and the context owns the response body lifecycle.

The streamed response exposes metadata immediately after response headers are
received:

- `status_code`
- `headers`
- `url`
- `request`
- `http_version`
- `elapsed`
- `history`
- status flags and `raise_for_status()`

Body bytes are read with `response.aiter_bytes()`.

```python
async with client.stream(GET, url) as response:
    response.raise_for_status()
    async for chunk in response.aiter_bytes():
        process(chunk)
```

Clean EOF marks the response body as completed. Leaving the context before EOF,
cancelling a body read, a body transport error, or a response-body read timeout
aborts the streamed body and releases the active request slot.

Manual cleanup is idempotent. Use `response.close()` when synchronous cleanup is
needed, or `await response.aclose()` when an async close shape is more convenient.

## Redirects

Redirect handling follows the same policy as buffered requests. Final response
metadata uses the final URL and `history` contains buffered redirect responses.

```python
async with foghttp.AsyncClient(follow_redirects=True) as client:
    async with client.stream(GET, "https://example.com/redirect") as response:
        print(response.url)
        print([item.status_code for item in response.history])
```

Redirect response bodies are buffered so history remains inspectable. The final
response body is streamed.

## Timeouts

For async streaming responses:

- `pool` controls waiting for an active request slot.
- `total` covers acquire, redirect hops, and response headers before the
  streamed response is returned.
- `read` controls progress while waiting for the next streamed body chunk.
- `write` is still reserved for future streaming upload work.

`ReadTimeout` during `aiter_bytes()` aborts the streamed body and exposes
`diagnostic.phase == "response_body"`.

Use `asyncio.timeout()` when application code needs a wall-clock limit for the
whole streaming consumption phase.

```python
try:
    async with asyncio.timeout(5.0):
        async with client.stream(GET, url) as response:
            async for chunk in response.aiter_bytes():
                process(chunk)
except TimeoutError:
    pass
```

## Current Boundaries

The current streaming API is intentionally narrow:

- async response body streaming only
- bytes only
- no sync `Client.stream()` yet
- no text or line iterator yet
- no streaming response decompression yet
- no streaming uploads yet

Buffered responses still support transparent `gzip`, `deflate`, and `br`
decoding. Streaming responses expose response body bytes after HTTP transfer
framing, without content-encoding decompression.
