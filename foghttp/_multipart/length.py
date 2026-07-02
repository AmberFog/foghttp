from .constants import CRLF
from .encoding import closing_boundary, field_header, file_header
from .models import MultipartField, MultipartFile, MultipartPayload


def multipart_content_length(payload: MultipartPayload) -> int | None:
    file_length = _files_content_length(payload.boundary, payload.files)
    if file_length is None:
        return None
    closing_length = len(closing_boundary(payload.boundary))
    field_length = _fields_content_length(payload.boundary, payload.fields)
    return closing_length + field_length + file_length


def _fields_content_length(boundary: str, fields: tuple[MultipartField, ...]) -> int:
    return sum(_field_content_length(boundary, field) for field in fields)


def _field_content_length(boundary: str, field: MultipartField) -> int:
    return len(field_header(boundary, field)) + len(field.content) + len(CRLF)


def _files_content_length(boundary: str, files: tuple[MultipartFile, ...]) -> int | None:
    total = 0
    for file in files:
        if file.content_length is None:
            return None
        total += len(file_header(boundary, file)) + file.content_length + len(CRLF)
    return total
