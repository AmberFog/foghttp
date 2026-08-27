from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterable, Iterator
import sys
from typing import cast

from .._upload_body import cleanup as upload_cleanup
from .._upload_body.chunks import body_chunk
from .._upload_body.thread_bridge import run_daemon_callbacks_bounded
from ..messages import MULTIPART_FILES_UNSUPPORTED
from .cleanup import MultipartFileCleanup
from .constants import CRLF
from .encoding import field_header
from .models import MultipartField, MultipartFile
from .sync_runner import SyncIteratorRunner


def iter_fields(boundary: str, fields: tuple[MultipartField, ...]) -> Iterator[bytes]:
    for field in fields:
        yield field_header(boundary, field)
        yield field.content
        yield CRLF


def iter_file_content(
    file: MultipartFile,
    cleanup: MultipartFileCleanup | None = None,
) -> Iterator[bytes]:
    if isinstance(file.content, bytes):
        yield file.content
        return
    if not isinstance(file.content, Iterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    iterator = iter(cast("Iterable[object]", file.content))
    if cleanup is not None:
        cleanup.track_iterator(iterator, file.content)
    try:
        for chunk in iterator:
            yield body_chunk(chunk)
    finally:
        if cleanup is None:
            _close_sync_iterator(iterator, file.content)


async def aiter_file_content(
    file: MultipartFile,
    cleanup: MultipartFileCleanup | None = None,
) -> AsyncGenerator[bytes, None]:
    if not isinstance(file.content, AsyncIterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    iterator = aiter(cast("AsyncIterable[object]", file.content))
    if cleanup is not None:
        cleanup.track_iterator(iterator, file.content)
    try:
        async for chunk in iterator:
            yield body_chunk(chunk)
    finally:
        if cleanup is None:
            await _close_async_iterator(iterator, file.content)


async def aiter_sync_file_content(
    file: MultipartFile,
    cleanup: MultipartFileCleanup | None = None,
) -> AsyncGenerator[bytes, None]:
    iterator = iter_file_content(file, cleanup)
    runner = SyncIteratorRunner(iterator)
    try:
        while True:
            chunk = await runner.next()
            if not isinstance(chunk, bytes):
                return
            yield chunk
    finally:
        await _close_sync_runner(runner)


async def _close_sync_runner(runner: SyncIteratorRunner) -> None:
    active_error = sys.exception()
    if runner.close():
        return
    try:
        await runner.wait_closed_bounded()
    except BaseException:
        if active_error is None:
            raise


def _close_sync_iterator(iterator: Iterator[object], source: object) -> None:
    if iterator is source:
        return
    active_error = sys.exception()
    iterator_cleanup = upload_cleanup.UploadSourceCleanup(iterator)
    cleanup_error = run_daemon_callbacks_bounded(
        (iterator_cleanup.interrupt,),
        timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
    )
    if cleanup_error is not None and active_error is None:
        raise cleanup_error


async def _close_async_iterator(
    iterator: AsyncIterator[object] | Iterator[object],
    source: object | None,
) -> None:
    if iterator is source:
        return
    active_error = sys.exception()
    try:
        await upload_cleanup.UploadSourceCleanup(iterator).aclose()
    except BaseException:
        if active_error is None:
            raise
