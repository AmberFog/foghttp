from contextlib import suppress
from dataclasses import replace
from inspect import isawaitable
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import Callable

from .._upload_body import (
    cleanup as upload_cleanup,
    file_source as upload_file_source,
    predicates as upload_predicates,
)
from ..messages import MULTIPART_FILES_UNSUPPORTED
from . import models as multipart_models
from .cleanup import MultipartFileCleanup


def fresh_payload(
    payload: multipart_models.MultipartPayload,
) -> tuple[
    multipart_models.MultipartPayload,
    tuple[MultipartFileCleanup, ...],
    BaseException | None,
]:
    files: list[multipart_models.MultipartFile] = []
    cleanups: list[MultipartFileCleanup] = []
    for file in payload.files:
        try:
            prepared = _fresh_file(file)
        except BaseException as error:  # noqa: BLE001
            return replace(payload, files=tuple(files)), tuple(cleanups), error
        files.append(prepared[0])
        cleanups.append(prepared[1])
        if prepared[2] is not None:
            return replace(payload, files=tuple(files)), tuple(cleanups), prepared[2]
    return replace(payload, files=tuple(files)), tuple(cleanups), None


def _fresh_file(
    file: multipart_models.MultipartFile,
) -> tuple[multipart_models.MultipartFile, MultipartFileCleanup, BaseException | None]:
    if not file.source_factory:
        return file, MultipartFileCleanup(file), None
    reservation = upload_cleanup.reserve_cleanup()
    try:
        content = cast("Callable[[], object]", file.content)()
    except BaseException:
        reservation.release()
        raise
    file = replace(file, content=content, source_factory=False, close_source=True)
    cleanup = MultipartFileCleanup(
        file,
        source_cleanup=upload_cleanup.UploadSourceCleanup(content, reservation=reservation),
    )
    try:
        content, async_source = _classify_file_content(content)
    except BaseException as error:  # noqa: BLE001
        with suppress(BaseException):
            cleanup.close()
        return file, cleanup, error
    return replace(file, content=content, async_source=async_source), cleanup, None


def _classify_file_content(content: object) -> tuple[object, bool]:
    if isawaitable(content):
        raise TypeError(MULTIPART_FILES_UNSUPPORTED)
    if upload_predicates.is_binary_file(content):
        content = upload_file_source.FileUploadSource(content)
    return content, upload_predicates.is_async_stream(content)
