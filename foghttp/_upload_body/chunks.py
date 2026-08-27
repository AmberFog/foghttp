from typing import TYPE_CHECKING, cast

from ..messages import STREAMING_BODY_CHUNK_UNSUPPORTED


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator


def body_chunk(content: object) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, memoryview):
        return content.tobytes()
    raise TypeError(STREAMING_BODY_CHUNK_UNSUPPORTED)


def sync_body_chunks(
    source: object,
    content_length: int | None,
) -> "Iterator[tuple[bytes, bool]]":
    remaining = content_length
    if remaining == 0:
        return
    iterator = iter(cast("Iterable[object]", source))
    yield from _sync_iterator_chunks(iterator, remaining)


async def async_body_chunks(
    source: object,
    content_length: int | None,
) -> "AsyncIterator[tuple[bytes, bool]]":
    remaining = content_length
    if remaining == 0:
        return
    iterator = aiter(cast("AsyncIterable[object]", source))
    async for chunk in _async_iterator_chunks(iterator, remaining):
        yield chunk


def _sync_iterator_chunks(
    iterator: "Iterator[object]",
    remaining: int | None,
) -> "Iterator[tuple[bytes, bool]]":
    for raw_chunk in iterator:
        chunk = body_chunk(raw_chunk)
        final, remaining = _chunk_progress(chunk, remaining)
        yield chunk, final
        if final:
            return


async def _async_iterator_chunks(
    iterator: "AsyncIterator[object]",
    remaining: int | None,
) -> "AsyncIterator[tuple[bytes, bool]]":
    async for raw_chunk in iterator:
        chunk = body_chunk(raw_chunk)
        final, remaining = _chunk_progress(chunk, remaining)
        yield chunk, final
        if final:
            return


def _chunk_progress(chunk: bytes, remaining: int | None) -> tuple[bool, int | None]:
    if remaining is None:
        return False, None
    updated = remaining - len(chunk)
    return updated <= 0, updated
