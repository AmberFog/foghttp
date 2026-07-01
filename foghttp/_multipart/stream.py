import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from typing import cast

from .._upload_body.feeders import close_async_source, close_sync_source
from .._upload_body.predicates import is_async_stream
from .constants import CRLF
from .encoding import closing_boundary, file_header
from .iterators import (
    aiter_file_content,
    aiter_sync_file_content,
    iter_fields,
    iter_file_content,
)
from .models import MultipartFile, MultipartPayload


class MultipartStream:
    def __init__(self, payload: MultipartPayload) -> None:
        self._payload = payload

    def __iter__(self) -> Iterator[bytes]:
        yield from iter_fields(self._payload.boundary, self._payload.fields)
        for file in self._payload.files:
            yield file_header(self._payload.boundary, file)
            yield from iter_file_content(file)
            yield CRLF
        yield closing_boundary(self._payload.boundary)

    def close(self) -> None:
        for file in self._payload.files:
            if file.close_source:
                close_sync_source(file.content)


class AsyncMultipartStream:
    def __init__(self, payload: MultipartPayload) -> None:
        self._payload = payload

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def aclose(self) -> None:
        close_tasks = [close_async_source(file.content) for file in self._payload.files if file.close_source]
        if close_tasks:
            await asyncio.gather(*close_tasks)

    async def _iterate(self) -> AsyncIterator[bytes]:
        for chunk in iter_fields(self._payload.boundary, self._payload.fields):
            yield chunk
        for file in self._payload.files:
            yield file_header(self._payload.boundary, file)
            if file.async_source:
                async for chunk in aiter_file_content(file):
                    yield chunk
            else:
                async for chunk in aiter_sync_file_content(file):
                    yield chunk
            yield CRLF
        yield closing_boundary(self._payload.boundary)


class MultipartStreamFactory:
    def __init__(self, payload: MultipartPayload) -> None:
        self._payload = payload

    def __call__(self) -> MultipartStream | AsyncMultipartStream:
        payload = _fresh_payload(self._payload)
        if payload.async_source:
            return AsyncMultipartStream(payload)
        return MultipartStream(payload)


def multipart_buffer(payload: MultipartPayload) -> bytes:
    return b"".join(MultipartStream(payload))


def _fresh_payload(payload: MultipartPayload) -> MultipartPayload:
    files = tuple(_fresh_file(file) for file in payload.files)
    return replace(payload, files=files)


def _fresh_file(file: MultipartFile) -> MultipartFile:
    if not file.source_factory:
        return file
    source_factory = cast("Callable[[], object]", file.content)
    content = source_factory()
    return replace(
        file,
        content=content,
        async_source=is_async_stream(content),
        source_factory=False,
        close_source=True,
    )
