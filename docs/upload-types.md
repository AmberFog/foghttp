# Upload Typing Contracts

FogHTTP exposes public typing contracts for streaming request body providers and
the multipart upload APIs planned later in the `0.3.5` release scope. These
names let application code and wrappers type body providers without importing
internal classes.

The runtime request API accepts streaming bodies through `content=`. Multipart
`files=` uploads are still planned separately.

## Public Types

Import upload contracts from `foghttp.types`:

```python
from collections.abc import Iterator

from foghttp.types import SyncByteStream, SyncByteStreamFactory


class Chunks:
    def __iter__(self) -> Iterator[bytes]:
        yield b"chunk"


def replayable_chunks() -> SyncByteStream:
    return Chunks()


stream: SyncByteStream = Chunks()
factory: SyncByteStreamFactory = replayable_chunks
```

Available contracts:

| Type | Meaning |
|---|---|
| `BodyChunk` | A request body chunk: `bytes`, `bytearray`, or `memoryview`. |
| `SyncByteStream` | Sync iterable body provider yielding bytes-like chunks. |
| `AsyncByteStream` | Async iterable body provider yielding bytes-like chunks. |
| `SyncByteStreamFactory` | Callable that returns a fresh sync byte stream for each send attempt. |
| `AsyncByteStreamFactory` | Callable that returns a fresh async byte stream for each send attempt. |
| `BinaryFile` | Binary file-like object with `read(size: int = -1, /) -> bytes`. |
| `SyncMultipartFileContent` | Bytes, binary file, sync byte stream, or sync byte-stream factory for a file part. |
| `SyncMultipartFileTuple` | `(filename, content)` or `(filename, content, content_type)` for sync multipart APIs. |
| `SyncMultipartFileValue` | Sync file content or sync file tuple. |
| `SyncMultipartFiles` | Mapping or repeated pairs of sync multipart file values. |
| `AsyncMultipartFileContent` | Bytes, binary file, async byte stream, or async byte-stream factory for a file part. |
| `AsyncMultipartFileTuple` | `(filename, content)` or `(filename, content, content_type)` for async multipart APIs. |
| `AsyncMultipartFileValue` | Async file content or async file tuple. |
| `AsyncMultipartFiles` | Mapping or repeated pairs of async multipart file values. |

## Replayability

Streaming and file-backed `content=` bodies are non-replayable by default.
Method-preserving redirects fail closed instead of replaying a consumed
provider. Buffered `bytes` and `str` bodies remain replayable.

Factory-backed `content=` bodies are replayable because FogHTTP calls the
factory for each send attempt. The factory must return a fresh, independent
stream with the same bytes each time.

Do not model replayability as a public boolean. Future redirect, retry, auth
refresh, and multipart logic will use provider/factory shape to decide whether a
body can be safely replayed.

## Ownership And Cleanup

Passing a direct streaming or file-like provider to `content=` transfers
request-scope cleanup ownership to FogHTTP. Providers are closed after use when
they expose `close()` or `aclose()`. Cleanup runs on success, timeout,
cancellation, redirect rejection, transport error, and client close.

Use a zero-argument factory when caller code needs to keep ownership of the
outer object or reopen a fresh provider for each replay attempt. The factory
itself is not closed; providers returned by the factory are closed after their
request attempt.

Providers should yield `bytes`, `bytearray`, or `memoryview` chunks. Mutable
chunks are copied before they cross the Rust transport boundary. Text, paths,
and arbitrary iterables are not upload chunks; callers should encode or open
them explicitly before passing them through streaming `content=`.
