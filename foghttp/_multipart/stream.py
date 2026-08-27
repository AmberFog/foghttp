import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing, suppress
from dataclasses import replace
from inspect import isawaitable
from typing import cast

from .._upload_body import (
    cleanup as upload_cleanup,
    file_source as upload_file_source,
    predicates as upload_predicates,
)
from ..messages import MULTIPART_FILES_UNSUPPORTED
from . import (
    iterators as multipart_iterators,
    models as multipart_models,
)
from .cleanup import MultipartFileCleanup
from .constants import CRLF
from .encoding import closing_boundary, file_header


class MultipartStream:
    def __init__(self, payload: multipart_models.MultipartPayload) -> None:
        self._payload = payload
        self._cleanups = tuple(MultipartFileCleanup(file) for file in payload.files)

    def __iter__(self) -> Iterator[bytes]:
        yield from multipart_iterators.iter_fields(self._payload.boundary, self._payload.fields)
        for file, cleanup in zip(self._payload.files, self._cleanups, strict=True):
            yield file_header(self._payload.boundary, file)
            yield from multipart_iterators.iter_file_content(file, cleanup)
            yield CRLF
        yield closing_boundary(self._payload.boundary)

    def close(self) -> None:
        first_error: BaseException | None = None
        for cleanup in self._cleanups:
            try:
                cleanup.close()
            except BaseException as error:  # noqa: BLE001
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


class AsyncMultipartStream:
    def __init__(self, payload: multipart_models.MultipartPayload) -> None:
        self._payload = payload
        self._cleanups = tuple(MultipartFileCleanup(file) for file in payload.files)

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def aclose(self) -> None:
        tasks = tuple(
            task
            for task in map(
                MultipartFileCleanup.start_async_cleanup,
                self._cleanups,
            )
            if task is not None
        )
        if not tasks:
            return
        done, _pending = await asyncio.wait(
            tasks,
            timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
        )
        cleanup_error = _first_cleanup_error(tasks, done)
        if cleanup_error is None:
            return
        raise cleanup_error

    async def _iterate(self) -> AsyncIterator[bytes]:
        for chunk in multipart_iterators.iter_fields(
            self._payload.boundary,
            self._payload.fields,
        ):
            yield chunk
        for file, cleanup in zip(self._payload.files, self._cleanups, strict=True):
            yield file_header(self._payload.boundary, file)
            iterator = (
                multipart_iterators.aiter_file_content(file, cleanup)
                if file.async_source
                else multipart_iterators.aiter_sync_file_content(file, cleanup)
            )
            async with aclosing(iterator):
                async for chunk in iterator:
                    yield chunk
            yield CRLF
        yield closing_boundary(self._payload.boundary)


class MultipartStreamFactory:
    def __init__(self, payload: multipart_models.MultipartPayload) -> None:
        self._payload = payload

    def __call__(
        self,
    ) -> MultipartStream | AsyncMultipartStream | upload_cleanup.UploadSourceFactoryFailure:
        payload, source_error = _fresh_payload(self._payload)
        stream = AsyncMultipartStream(payload) if payload.async_source else MultipartStream(payload)
        if source_error is not None:
            return upload_cleanup.UploadSourceFactoryFailure(stream, source_error)
        return stream


def multipart_buffer(payload: multipart_models.MultipartPayload) -> bytes:
    return b"".join(MultipartStream(payload))


def _first_cleanup_error(
    tasks: tuple[asyncio.Task[None], ...],
    done: set[asyncio.Task[None]],
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    for task in tasks:
        if task not in done:
            continue
        try:
            task.result()
        except BaseException as error:  # noqa: BLE001
            if cleanup_error is None:
                cleanup_error = error
    return cleanup_error


def _fresh_payload(
    payload: multipart_models.MultipartPayload,
) -> tuple[multipart_models.MultipartPayload, BaseException | None]:
    files: list[multipart_models.MultipartFile] = []
    try:
        files.extend(_fresh_file(file) for file in payload.files)
    except BaseException as exc:  # noqa: BLE001
        return replace(payload, files=tuple(files)), exc
    return replace(payload, files=tuple(files)), None


def _fresh_file(file: multipart_models.MultipartFile) -> multipart_models.MultipartFile:
    if not file.source_factory:
        return file
    source_factory = cast("Callable[[], object]", file.content)
    content = source_factory()
    if isawaitable(content):
        upload_cleanup.close_sync_source(content)
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    try:
        if upload_predicates.is_binary_file(content):
            content = upload_file_source.FileUploadSource(content)
        async_source = upload_predicates.is_async_stream(content)
    except BaseException:
        with suppress(BaseException):
            upload_cleanup.close_sync_source(content)
        raise
    return replace(
        file,
        content=content,
        async_source=async_source,
        source_factory=False,
        close_source=True,
    )
