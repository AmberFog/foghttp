__all__ = (
    "assert_multipart_parts",
    "multipart_parts_from_payload",
    "parse_multipart_parts",
)

from email.parser import BytesParser
from email.policy import default
from typing import Any

from .models import MultipartPart


def multipart_parts_from_payload(payload: dict[str, Any]) -> list[MultipartPart]:
    content_type = payload["headers"]["content-type"][0]
    return parse_multipart_parts(
        content_type=content_type,
        body=payload["body"].encode(),
    )


def parse_multipart_parts(*, content_type: str, body: bytes) -> list[MultipartPart]:
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body,
    )
    return [
        MultipartPart(
            name=str(part.get_param("name", header="content-disposition")),
            filename=_optional_string(part.get_param("filename", header="content-disposition")),
            content=_decoded_payload(part.get_payload(decode=True)),
            content_type=part["content-type"],
        )
        for part in message.iter_parts()
    ]


def assert_multipart_parts(actual: list[MultipartPart], expected: list[MultipartPart]) -> None:
    assert actual == expected  # noqa: S101


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _decoded_payload(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    return b""
