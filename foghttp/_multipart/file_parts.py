from collections.abc import Mapping, Sequence
from typing import TypeAlias, cast

from .._upload_body.file_source import FileUploadSource, file_content_length
from .._upload_body.predicates import is_async_stream, is_binary_file, is_sync_stream
from ..messages import MULTIPART_FILES_UNSUPPORTED
from .constants import DEFAULT_FILE_CONTENT_TYPE
from .models import MultipartFile
from .values import body_chunk, filename_from_content, filename_value, text_value


FileItems: TypeAlias = Mapping[str, object] | Sequence[tuple[str, object]]
FILE_TUPLE_WITHOUT_CONTENT_TYPE_SIZE = 2


def multipart_files(files: object) -> tuple[MultipartFile, ...]:
    if files is None:
        return ()
    try:
        return _multipart_file_parts(_iter_file_items(cast("FileItems", files)))
    except (TypeError, ValueError) as exc:
        raise TypeError(MULTIPART_FILES_UNSUPPORTED) from exc


def _iter_file_items(files: FileItems) -> list[tuple[str, object]]:
    items = files.items() if isinstance(files, Mapping) else files
    return [(text_value(raw_name), raw_value) for raw_name, raw_value in items]


def _multipart_file_parts(file_items: list[tuple[str, object]]) -> tuple[MultipartFile, ...]:
    parts: list[MultipartFile] = []
    for field_name, value in file_items:
        parts.append(_file_part(field_name, value))
    return tuple(parts)


def _file_part(field_name: str, value: object) -> MultipartFile:
    filename, content, content_type = _file_value(value, field_name)
    return _content_file_part(
        field_name=field_name,
        filename=filename,
        content=content,
        content_type=content_type,
    )


def _file_value(value: object, field_name: str) -> tuple[str, object, str]:
    if _is_file_tuple(value):
        tuple_value = cast("tuple[object, ...]", value)
        content_type = (
            DEFAULT_FILE_CONTENT_TYPE
            if len(tuple_value) == FILE_TUPLE_WITHOUT_CONTENT_TYPE_SIZE
            else text_value(tuple_value[2])
        )
        return filename_value(tuple_value[0]), tuple_value[1], content_type
    return filename_from_content(value, fallback=field_name), value, DEFAULT_FILE_CONTENT_TYPE


def _content_file_part(
    *,
    field_name: str,
    filename: str,
    content: object,
    content_type: str,
) -> MultipartFile:
    if isinstance(content, bytes | bytearray | memoryview):
        body = body_chunk(content)
        return MultipartFile(
            name=field_name,
            filename=filename,
            content=body,
            content_type=content_type,
            content_length=len(body),
            replayable=True,
            async_source=False,
        )
    if is_binary_file(content):
        return MultipartFile(
            name=field_name,
            filename=filename,
            content=FileUploadSource(content),
            content_type=content_type,
            content_length=file_content_length(content),
            replayable=False,
            async_source=False,
        )
    if is_async_stream(content) or is_sync_stream(content):
        return MultipartFile(
            name=field_name,
            filename=filename,
            content=content,
            content_type=content_type,
            content_length=None,
            replayable=False,
            async_source=is_async_stream(content),
        )
    if callable(content):
        return MultipartFile(
            name=field_name,
            filename=filename,
            content=content,
            content_type=content_type,
            content_length=None,
            replayable=True,
            async_source=False,
            source_factory=True,
        )
    raise TypeError(MULTIPART_FILES_UNSUPPORTED)


def _is_file_tuple(value: object) -> bool:
    if not isinstance(value, tuple):
        return False
    return len(value) in (2, 3) and isinstance(value[0], str)
