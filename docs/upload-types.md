# Upload Typing Contracts

FogHTTP exposes public typing contracts for streaming request body providers and
multipart `files=` uploads. These names let application code and wrappers type
body providers without importing internal classes.

The runtime request API accepts streaming bodies through `content=` and
multipart uploads through `files=`.

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
| `SyncMultipartFileContent` | Bytes-like chunk, binary file, sync byte stream, or sync byte-stream factory for a file part. |
| `SyncMultipartFileTuple` | `(filename, content)` or `(filename, content, content_type)` for sync multipart APIs. |
| `SyncMultipartFileValue` | Sync file content or sync file tuple. |
| `SyncMultipartFiles` | Mapping or repeated pairs of sync multipart file values. |
| `AsyncMultipartFileContent` | Bytes-like chunk, binary file, sync or async byte stream, or sync/async byte-stream factory for an async multipart file part. |
| `AsyncMultipartFileTuple` | `(filename, content)` or `(filename, content, content_type)` for async multipart APIs. |
| `AsyncMultipartFileValue` | Async file content or async file tuple. |
| `AsyncMultipartFiles` | Mapping or repeated pairs of async multipart file values. |

## Replayability

Streaming and file-backed `content=` bodies are non-replayable by default.
Direct file-like and direct stream parts passed through `files=` are also
non-replayable. Method-preserving redirects fail closed instead of replaying a
consumed provider. Buffered `bytes` and `str` bodies remain replayable, and
bytes-like multipart file parts are replayable.

Factory-backed `content=` bodies and factory-backed multipart file parts are
replayable because FogHTTP calls the factory for each send attempt. The factory
must return a fresh, independent stream with the same bytes each time.

Do not mix multipart file factories with direct non-replayable file or stream
parts in the same request. FogHTTP rejects that shape because it would create a
body where only some parts can be safely replayed.

Do not model replayability as a public boolean. Future redirect, retry, auth
refresh, and multipart logic will use provider/factory shape to decide whether a
body can be safely replayed.

## Ownership And Cleanup

Passing a direct streaming or file-like provider to `content=` transfers
request-scope cleanup ownership to FogHTTP. Providers are closed after use when
they expose `close()` or `aclose()`. Cleanup runs on success, timeout,
cancellation, redirect rejection, transport error, and client close.

Passing a direct file-like or stream provider through `files=` does not transfer
ownership. The caller remains responsible for closing external file objects and
streams after the request completes. Providers returned by multipart factories
are request-attempt objects and FogHTTP closes them after that attempt.

Use a zero-argument factory when caller code needs to keep ownership of the
outer object or reopen a fresh provider for each replay attempt. The factory
itself is not closed; providers returned by the factory are closed after their
request attempt.

Providers should yield `bytes`, `bytearray`, or `memoryview` chunks. Mutable
chunks are copied before they cross the Rust transport boundary. Text, paths,
and arbitrary iterables are not upload chunks; callers should encode or open
them explicitly before passing them through streaming `content=`.
