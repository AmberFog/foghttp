# Upload Typing Contracts

FogHTTP exposes public typing contracts for the upload features planned in the
`0.3.5` release scope. These names are available now so application code,
wrappers, and future FogHTTP upload APIs can type body providers without
importing internal classes.

The runtime request API is still buffered-only today: `json=`, `data=`, and
`content=` accept the same values described in
[Request builder compatibility](./request-builder.md). Streaming request bodies
and `files=` multipart uploads will be implemented in later tasks.

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
| `BodyChunk` | A request body chunk, currently `bytes`. |
| `SyncByteStream` | Sync iterable body provider yielding `bytes` chunks. |
| `AsyncByteStream` | Async iterable body provider yielding `bytes` chunks. |
| `SyncByteStreamFactory` | Callable that returns a fresh sync byte stream. |
| `AsyncByteStreamFactory` | Callable that returns a fresh async byte stream. |
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

Streaming and file-backed bodies are non-replayable by default. A body is
replayable only when the caller provides a factory that can create a fresh,
independent stream with the same bytes for each send attempt.

Do not model replayability as a public boolean. Future redirect, retry, auth
refresh, and multipart logic will use provider/factory shape to decide whether a
body can be safely replayed.

## Ownership And Cleanup

The caller owns body providers and file objects passed to FogHTTP unless the
future API explicitly documents that FogHTTP opened the resource. Future upload
implementations must close FogHTTP-owned resources on success, timeout,
cancellation, redirect rejection, transport error, and client close. Caller-owned
files remain the caller's responsibility unless the API says otherwise.

Providers should yield `bytes` chunks. Text, paths, and arbitrary iterables are
not upload chunks; callers should encode or open them explicitly before passing
them to a future streaming upload API.
