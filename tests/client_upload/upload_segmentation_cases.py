__all__ = (
    "RECOVERY_UPLOAD",
    "SEGMENTATION_PAYLOAD",
    "UPLOAD_GATE_TIMEOUT",
    "AsyncSnapshotGate",
    "MutableUploadChunk",
    "SyncSnapshotGate",
    "assert_segmented_upload",
    "async_upload_chunks",
    "upload_request_options",
)

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
import threading
from typing import TYPE_CHECKING, Any

from tests.client_multipart.assertions import assert_multipart_parts, multipart_parts_from_payload
from tests.client_multipart.models import MultipartPart


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


SEGMENTATION_PAYLOAD = b"".join(f"segment:{index:05d}|".encode() for index in range(16_387))
RECOVERY_UPLOAD = b"upload-budget-recovered"
UPLOAD_GATE_TIMEOUT = 5.0
SNAPSHOT_GATE_NOT_RELEASED = "upload snapshot gate was not released"


@dataclass(slots=True)
class MutableUploadChunk:
    backing: bytearray
    chunk: bytearray | memoryview

    def mutate(self) -> None:
        self.backing[:] = b"x" * len(self.backing)


@dataclass(slots=True)
class SyncSnapshotGate:
    expected: bytes
    captured: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def hold(self, chunk: bytes) -> None:
        if chunk != self.expected:
            return
        self.captured.set()
        if not self.release.wait(UPLOAD_GATE_TIMEOUT):
            raise TimeoutError(SNAPSHOT_GATE_NOT_RELEASED)


@dataclass(slots=True)
class AsyncSnapshotGate:
    expected: bytes
    captured: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def hold(self, chunk: bytes) -> None:
        if chunk != self.expected:
            return
        self.captured.set()
        await asyncio.wait_for(self.release.wait(), timeout=UPLOAD_GATE_TIMEOUT)


async def async_upload_chunks(chunk: bytes | bytearray | memoryview) -> "AsyncIterator[bytes | bytearray | memoryview]":
    yield chunk


def upload_request_options(source: object, upload_mode: str) -> dict[str, Any]:
    if upload_mode == "multipart":
        return {
            "data": {"description": "segmented upload"},
            "files": {"file": ("segments.bin", source, "application/octet-stream")},
        }
    return {"content": source}


def assert_segmented_upload(payload: dict[str, Any], expected: bytes, upload_mode: str) -> None:
    if upload_mode == "multipart":
        parts = multipart_parts_from_payload(payload)
        assert_multipart_parts(
            parts,
            [
                MultipartPart(name="description", content=b"segmented upload"),
                MultipartPart(
                    name="file",
                    content=expected,
                    filename="segments.bin",
                    content_type="application/octet-stream",
                ),
            ],
        )
        received = parts[1].content
        boundary = payload["headers"]["content-type"][0].split("boundary=", maxsplit=1)[1]
        assert payload["body"].encode().endswith(f"--{boundary}--\r\n".encode())  # noqa: S101
    else:
        received = payload["body"].encode()
        assert received == expected  # noqa: S101
    assert sha256(received).digest() == sha256(expected).digest()  # noqa: S101
    assert payload["headers"]["content-length"] == []  # noqa: S101
    assert payload["headers"]["transfer-encoding"] == ["chunked"]  # noqa: S101
