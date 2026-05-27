# Response Streaming

FogHTTP supports response streaming through `Client.stream()` and
`AsyncClient.stream()`. Bytes are the source of truth, and text/line helpers are
thin incremental layers over the same body stream.

Use it when the response body should be consumed incrementally instead of being
fully buffered into `Response.content`.

```python
import foghttp
from foghttp.methods import GET


with foghttp.Client() as client:
    with client.stream(GET, "https://httpbin.org/stream-bytes/65536") as response:
        response.raise_for_status()

        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)

        print(response.status_code, total)
```

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

`Client.stream()` returns a context manager. `AsyncClient.stream()` returns an
async context manager. The request is sent when the context is entered, and the
context owns the response body lifecycle.

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

The body can be consumed once through one of these iterator families:

- `iter_bytes()` / `aiter_bytes()`
- `iter_text()` / `aiter_text()`
- `iter_lines()` / `aiter_lines()`

Calling another body iterator after consumption has started raises
`LifecycleError`.

```python
with client.stream(GET, url) as response:
    response.raise_for_status()
    for chunk in response.iter_bytes():
        process(chunk)
```

```python
async with client.stream(GET, url) as response:
    response.raise_for_status()
    async for chunk in response.aiter_bytes():
        process(chunk)
```

Text streaming uses an incremental decoder, so multibyte characters can span
byte chunk boundaries. By default it uses a valid `charset` from
`Content-Type`; otherwise it falls back to `utf-8`. Streaming text does not
inspect a body BOM because the body is consumed incrementally. Override the
decoder when needed:

```python
with client.stream(GET, url) as response:
    for text in response.iter_text(encoding="utf-8", errors="replace"):
        process_text(text)
```

Text and line iterators decode the streamed bytes as delivered after HTTP
transfer framing. They do not transparently decompress `gzip`, `deflate`, or
`br` response bodies yet. Use buffered responses for transparent decompression,
or request an uncompressed response when streaming text or lines.

Line streaming strips line endings and handles `LF`, `CRLF`, empty lines, and a
final line without a trailing newline. Because a line iterator must buffer text
until the next delimiter, FogHTTP limits one streamed line to `1048576`
characters by default. Pass `max_line_chars=` to choose another limit, or
`max_line_chars=None` only for trusted streams where unbounded lines are
intentional:

```python
async with client.stream(GET, url) as response:
    async for line in response.aiter_lines(max_line_chars=256 * 1024):
        process_line(line)
```

Clean EOF marks the response body as completed. Leaving the context before EOF,
cancelling a body read, a body transport error, or a response-body read timeout
aborts the streamed body and releases the active request slot.

Manual cleanup is idempotent. Use `response.close()` when synchronous cleanup is
needed. Async stream responses also expose `await response.aclose()` when an
async close shape is more convenient.

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

For streaming responses:

- `pool` controls waiting for an active request slot.
- `total` covers acquire, redirect hops, and response headers before the
  streamed response is returned.
- `read` controls progress while waiting for the next streamed body chunk.
- `write` is still reserved for future streaming upload work.

`ReadTimeout` during `iter_bytes()` or `aiter_bytes()` aborts the streamed body
and exposes `diagnostic.phase == "response_body"`.

For async callers, use `asyncio.timeout()` when application code needs a
wall-clock limit for the whole streaming consumption phase.

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

- bytes, text, and line iteration only
- no streaming response decompression yet
- no streaming uploads yet

Buffered responses still support transparent `gzip`, `deflate`, and `br`
decoding. Streaming responses expose response body bytes after HTTP transfer
framing, without content-encoding decompression.
