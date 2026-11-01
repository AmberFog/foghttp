import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing

from .._upload_body import cleanup as upload_cleanup
from . import (
    iterators as multipart_iterators,
    models as multipart_models,
)
from .cleanup import MultipartFileCleanup
from .constants import CRLF
from .encoding import closing_boundary, file_header
from .factory import fresh_payload


class MultipartStream:
    def __init__(
        self,
        payload: multipart_models.MultipartPayload,
        *,
        cleanups: tuple[MultipartFileCleanup, ...] | None = None,
    ) -> None:
        self._payload = payload
        if cleanups is None:
            cleanups = tuple(MultipartFileCleanup(file) for file in payload.files)
        self._cleanups = cleanups

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
    def __init__(
        self,
        payload: multipart_models.MultipartPayload,
        *,
        cleanups: tuple[MultipartFileCleanup, ...] | None = None,
    ) -> None:
        self._payload = payload
        if cleanups is None:
            cleanups = tuple(MultipartFileCleanup(file) for file in payload.files)
        self._cleanups = cleanups

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
        payload, cleanups, source_error = fresh_payload(self._payload)
        stream = (
            AsyncMultipartStream(payload, cleanups=cleanups)
            if payload.async_source
            else MultipartStream(payload, cleanups=cleanups)
        )
        if source_error is not None:
            return upload_cleanup.UploadSourceFactoryFailure(stream, source_error)
        return stream


def multipart_buffer(payload: multipart_models.MultipartPayload) -> bytes:
    return b"".join(MultipartStream(payload))


def _first_cleanup_error(
    tasks: tuple[asyncio.Future[None], ...],
    done: set[asyncio.Future[None]],
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
