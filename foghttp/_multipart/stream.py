import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import Future
from contextlib import aclosing

from .._upload_body import cleanup as upload_cleanup
from .._upload_body.cleanup_group import CleanupGroup, GroupedUploadSource
from .._upload_body.cleanup_start import collect_worker_interrupts, defer_worker_interrupts
from . import (
    iterators as multipart_iterators,
    models as multipart_models,
)
from .cleanup import MultipartFileCleanup
from .constants import CRLF
from .encoding import closing_boundary, file_header
from .factory import fresh_payload


class _MultipartCleanupGroup(GroupedUploadSource):
    async_parts = False

    def __init__(
        self,
        payload: multipart_models.MultipartPayload,
        *,
        cleanups: tuple[MultipartFileCleanup, ...] | None = None,
    ) -> None:
        self._payload = payload
        self.needs_request_loop = self.async_parts or any(file.async_source is None for file in payload.files)
        if cleanups is None:
            cleanups = tuple(MultipartFileCleanup(file) for file in payload.files)
        self._cleanups = cleanups

    def start_parts(self, *, on_loop: bool) -> CleanupGroup:
        with collect_worker_interrupts() as interrupts:
            owners = self._start_part_owners(on_loop=on_loop)
            start_error = next(iter(interrupts), None)
        parts = [owner.completion for owner in owners]
        if start_error is not None:
            startup: Future[None] = Future()
            startup.set_exception(start_error)
            parts.insert(0, startup)
        return CleanupGroup(tuple(parts))

    @defer_worker_interrupts()
    def _start_part_owners(self, *, on_loop: bool) -> tuple[upload_cleanup.UploadSourceCleanup, ...]:
        owners = []
        for file, cleanup in zip(self._payload.files, self._cleanups, strict=True):
            prefer_async = on_loop if file.async_source is None else self.async_parts
            owner = cleanup.start_part(on_loop=on_loop and prefer_async, prefer_async=prefer_async)
            if owner is not None:
                owners.append(owner)
        return tuple(owners)


class MultipartStream(_MultipartCleanupGroup):
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


class AsyncMultipartStream(_MultipartCleanupGroup):
    async_parts = True

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def aclose(self) -> None:
        tasks = tuple(owner.waiters.future() for owner in self._start_part_owners(on_loop=True))
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
