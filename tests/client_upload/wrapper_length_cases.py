__all__ = (
    "WRAPPER_SOURCE_KINDS",
    "WrapperLengthCase",
    "assert_received_content",
    "assert_received_multipart",
    "wrapper_length_case",
)

import bz2
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import gzip
from hashlib import sha256
import io
from typing import TYPE_CHECKING, Any, cast

from tests.client_multipart.assertions import assert_multipart_parts, multipart_parts_from_payload
from tests.client_multipart.models import MultipartPart
from tests.client_upload.file_length_sources import buffered_write_source


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO


WRAPPER_SOURCE_KINDS = ("gzip", "bz2", "regular_offset", "bytesio_offset", "gzip_factory", "buffered_raw_write")
WRAPPER_PAYLOAD = b"a" * 1000
FILE_OFFSET = 113


@dataclass(frozen=True, slots=True)
class WrapperLengthCase:
    source: object
    expected: bytes
    known_length: bool
    factory_owned: bool
    opened: list["BinaryIO"]


@contextmanager
def wrapper_length_case(tmp_path: "Path", source_kind: str) -> "Iterator[WrapperLengthCase]":
    with ExitStack() as cleanup:
        opened: list[BinaryIO] = []
        source_path = tmp_path / "wrapper-payload.bin"
        source_path.write_bytes(gzip.compress(WRAPPER_PAYLOAD, compresslevel=9, mtime=0))

        def gzip_source() -> "BinaryIO":
            source = cast("BinaryIO", cleanup.enter_context(gzip.open(source_path, "rb")))
            opened.append(source)
            return source

        if source_kind == "gzip_factory":
            yield WrapperLengthCase(
                gzip_source,
                WRAPPER_PAYLOAD,
                known_length=False,
                factory_owned=True,
                opened=opened,
            )
            return
        if source_kind == "gzip":
            source = gzip_source()
        elif source_kind == "bz2":
            source_path.write_bytes(bz2.compress(WRAPPER_PAYLOAD))
            source = cast("BinaryIO", cleanup.enter_context(bz2.open(source_path, "rb")))
            opened.append(source)
        elif source_kind == "regular_offset":
            source_path.write_bytes(WRAPPER_PAYLOAD)
            source = cleanup.enter_context(source_path.open("rb"))
            opened.append(source)
        elif source_kind == "bytesio_offset":
            source = cleanup.enter_context(io.BytesIO(WRAPPER_PAYLOAD))
            opened.append(source)
        elif source_kind == "buffered_raw_write":
            source = cleanup.enter_context(buffered_write_source(source_path, WRAPPER_PAYLOAD))
            opened.append(source)
        else:
            raise ValueError(source_kind)
        known_length = source_kind in {"regular_offset", "bytesio_offset"}
        if known_length:
            source.seek(FILE_OFFSET)
        expected = WRAPPER_PAYLOAD[FILE_OFFSET:] if known_length else WRAPPER_PAYLOAD
        yield WrapperLengthCase(source, expected, known_length, factory_owned=False, opened=opened)


def assert_received_content(payload: dict[str, Any], case: WrapperLengthCase) -> None:
    received = payload["body"].encode()
    assert received == case.expected  # noqa: S101
    assert sha256(received).digest() == sha256(case.expected).digest()  # noqa: S101
    _assert_framing(payload, known_length=case.known_length)
    if case.known_length:
        assert payload["headers"]["content-length"] == [str(len(case.expected))]  # noqa: S101


def assert_received_multipart(payload: dict[str, Any], case: WrapperLengthCase) -> None:
    parts = multipart_parts_from_payload(payload)
    assert_multipart_parts(
        parts,
        [
            MultipartPart(name="description", content=b"wrapper length"),
            MultipartPart(
                name="file",
                content=case.expected,
                filename="payload.bin",
                content_type="application/octet-stream",
            ),
        ],
    )
    assert sha256(parts[1].content).digest() == sha256(case.expected).digest()  # noqa: S101
    boundary = payload["headers"]["content-type"][0].split("boundary=", maxsplit=1)[1]
    assert payload["body"].encode().endswith(f"--{boundary}--\r\n".encode())  # noqa: S101
    _assert_framing(payload, known_length=case.known_length)


def _assert_framing(payload: dict[str, Any], *, known_length: bool) -> None:
    headers = payload["headers"]
    if known_length:
        assert headers["content-length"]  # noqa: S101
        assert headers["transfer-encoding"] == []  # noqa: S101
    else:
        assert headers["content-length"] == []  # noqa: S101
        assert headers["transfer-encoding"] == ["chunked"]  # noqa: S101
