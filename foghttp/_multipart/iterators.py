import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import cast

from ..messages import MULTIPART_FILES_UNSUPPORTED
from .constants import CRLF
from .encoding import field_header
from .models import MultipartField, MultipartFile
from .values import body_chunk


_ITER_DONE = object()


def iter_fields(boundary: str, fields: tuple[MultipartField, ...]) -> Iterator[bytes]:
    for field in fields:
        yield field_header(boundary, field)
        yield field.content
        yield CRLF


def iter_file_content(file: MultipartFile) -> Iterator[bytes]:
    if isinstance(file.content, bytes):
        yield file.content
        return
    if not isinstance(file.content, Iterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    for chunk in cast("Iterable[object]", file.content):
        yield body_chunk(chunk)


async def aiter_file_content(file: MultipartFile) -> "AsyncIterator[bytes]":
    if not isinstance(file.content, AsyncIterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    async for chunk in cast("AsyncIterable[object]", file.content):
        yield body_chunk(chunk)


async def aiter_sync_file_content(file: MultipartFile) -> "AsyncIterator[bytes]":
    iterator = iter_file_content(file)
    while True:
        chunk = await asyncio.to_thread(_next_sync_chunk, iterator)
        if chunk is _ITER_DONE:
            return
        yield cast("bytes", chunk)


def _next_sync_chunk(iterator: Iterator[bytes]) -> bytes | object:
    return next(iterator, _ITER_DONE)
