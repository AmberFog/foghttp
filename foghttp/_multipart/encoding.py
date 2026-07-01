from secrets import token_hex

from .constants import (
    BOUNDARY_BYTES,
    BOUNDARY_PREFIX,
    FORM_DATA_DISPOSITION,
)
from .models import MultipartField, MultipartFile
from .values import header_value, quoted_header_value


def generate_boundary() -> str:
    return f"{BOUNDARY_PREFIX}{token_hex(BOUNDARY_BYTES)}"


def field_header(boundary: str, field: MultipartField) -> bytes:
    return _part_header(
        boundary,
        disposition_params=(("name", field.name),),
    )


def file_header(boundary: str, file: MultipartFile) -> bytes:
    return _part_header(
        boundary,
        disposition_params=(
            ("name", file.name),
            ("filename", file.filename),
        ),
        content_type=file.content_type,
    )


def closing_boundary(boundary: str) -> bytes:
    return f"--{boundary}--\r\n".encode("ascii")


def _part_header(
    boundary: str,
    *,
    disposition_params: tuple[tuple[str, str], ...],
    content_type: str | None = None,
) -> bytes:
    header_text = _headers_text(disposition_params, content_type)
    return f"--{boundary}\r\n{header_text}\r\n\r\n".encode()


def _headers_text(
    disposition_params: tuple[tuple[str, str], ...],
    content_type: str | None,
) -> str:
    headers = [
        _disposition_header(disposition_params),
    ]
    if content_type is not None:
        headers.append(f"Content-Type: {header_value(content_type)}")
    return "\r\n".join(headers)


def _disposition_header(params: tuple[tuple[str, str], ...]) -> str:
    encoded_params = "; ".join(f'{name}="{quoted_header_value(value)}"' for name, value in params)
    return f"Content-Disposition: {FORM_DATA_DISPOSITION}; {encoded_params}"
