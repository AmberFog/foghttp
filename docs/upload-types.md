# Upload Typing Contracts

FogHTTP exposes public typing contracts for streaming request body providers and
multipart `files=` uploads. These names let application code and wrappers type
body providers without importing internal classes.

Request and response metadata contracts are documented separately in
[Public typing contracts](./typing.md).

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

Do not model replayability as a public boolean. Redirects and the opt-in
[retry policy](./retries.md) use provider/factory shape to decide whether a
body can be safely replayed; auth refresh runs before each resulting transport attempt.

## Ownership And Cleanup

| Body source | Ownership and cleanup |
|---|---|
| Buffered `bytes` or `str` through `content=` | FogHTTP copies or retains the immutable value for the request. There is no provider to close. |
| Mapping, repeated pairs, `bytes`, or `str` through `data=` | FogHTTP keeps an immutable `bytes` value as-is; `str`, mappings, and repeated pairs are encoded to buffered bytes while building the request. File-like objects, sync or async providers, and factories are unsupported: FogHTTP rejects them and leaves them caller-owned. When `data=` supplies multipart form fields alongside `files=`, those field values are also encoded eagerly. |
| Direct file-like or streaming provider through `content=` | Ownership transfers when FogHTTP hands a validated request to the transport, before pool admission or provider iteration. FogHTTP calls `close()` or `aclose()` after use on success, timeout, cancellation, redirect rejection, transport error, and client close. Before transport handoff, the caller owns the provider. |
| Zero-argument factory through `content=` | The factory remains caller-owned and is not closed. FogHTTP owns each returned provider and invokes its applicable cleanup method once after that request attempt. |
| Buffered bytes-like part through `files=` | FogHTTP copies mutable bytes-like values before transport use. There is no external provider to close. |
| Direct file-like or streaming part through `files=` | The provider remains caller-owned. FogHTTP consumes it but never calls `close()` or `aclose()`; the caller closes it after the request completes, including failure and cancellation paths. |
| Zero-argument part factory through `files=` | The factory remains caller-owned and is not closed. FogHTTP owns each returned provider and invokes its applicable cleanup method once after that multipart attempt. |

The direct-provider difference is intentional. A `content=` provider represents
the complete one-shot request body, so its lifetime is the request runtime's
cleanup responsibility. A direct `files=` provider is an externally supplied
multipart part, commonly managed by the caller's own context manager; closing it
inside FogHTTP would unexpectedly take ownership of that external resource.
Factories remove that ambiguity because every returned provider is a fresh
request-attempt object created solely for FogHTTP to consume.

FogHTTP-owned provider cleanup is best effort: FogHTTP invokes the applicable
`close()` or `aclose()` method at most once and suppresses cleanup errors so they
do not mask the request outcome. Waiting for `aclose()` is bounded so a broken
cleanup implementation cannot indefinitely hold request completion or
cancellation; the cleanup may continue in a dedicated daemon thread. An async
client does not run a synchronous provider's `close()` on its event-loop thread.
If a sync client must reject an async provider returned by a factory, `aclose()`
runs on a dedicated thread under the same best-effort contract.

Request construction, pre-transport validation, an unsent prepared request, and
a stream context that was created but never entered have not handed the request
to the transport. Their direct `content=` providers therefore remain
caller-owned and must be closed by the caller. A sync client also rejects a
direct async provider before transport handoff and does not call `aclose()` on
it. If an object is both callable and a file-like, sync-stream, or async-stream
provider, the direct provider capability takes precedence over factory
classification; the ownership and replayability rules for a direct provider
apply.

Providers should yield `bytes`, `bytearray`, or `memoryview` chunks. Mutable
chunks are copied before they cross the Rust transport boundary. Text, paths,
and arbitrary iterables are not upload chunks; callers should encode or open
them explicitly before passing them through streaming `content=`.
