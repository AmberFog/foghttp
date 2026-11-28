from collections.abc import AsyncGenerator, AsyncIterable, Generator, Iterable, Iterator
import sys
from typing import cast

from .._upload_body.chunks import body_chunk
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
) -> Generator[bytes, None, None]:
    if isinstance(file.content, bytes):
        yield file.content
        return
    if not isinstance(file.content, Iterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    iterator_owner = cleanup or MultipartFileCleanup(file, iterator_only=True)
    iterator = iterator_owner.create_iterator(lambda: iter(cast("Iterable[object]", file.content)), file.content)
    try:
        for chunk in iterator:
            yield body_chunk(chunk)
    finally:
        if cleanup is None:
            iterator_owner.close(preserve_error=True)


async def aiter_file_content(
    file: MultipartFile,
    cleanup: MultipartFileCleanup | None = None,
) -> AsyncGenerator[bytes, None]:
    if not isinstance(file.content, AsyncIterable):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    iterator_owner = cleanup or MultipartFileCleanup(file, iterator_only=True)
    iterator = iterator_owner.create_iterator(lambda: aiter(cast("AsyncIterable[object]", file.content)), file.content)
    try:
        async for chunk in iterator:
            yield body_chunk(chunk)
    finally:
        if cleanup is None:
            await iterator_owner.aclose(preserve_error=True)


async def aiter_sync_file_content(
    file: MultipartFile,
    cleanup: MultipartFileCleanup | None = None,
) -> AsyncGenerator[bytes, None]:
    iterator = iter_file_content(file, cleanup)
    # With an external part owner, closing this wrapper never closes the user's iterator.
    runner = SyncIteratorRunner(iterator, close_wrapper=None if cleanup is None else iterator.close)
    try:
        while True:
            chunk = await runner.next()
            if not isinstance(chunk, bytes):
                return
            yield chunk
    finally:
        if not runner.close():
            await runner.wait_closed_bounded(raise_on_error=sys.exception() is None)
