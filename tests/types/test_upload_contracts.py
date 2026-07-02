from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from pathlib import Path
from typing import assert_type

import foghttp.types as foghttp_types
from foghttp.types import (
    AsyncByteStream,
    AsyncByteStreamFactory,
    AsyncMultipartFileContent,
    AsyncMultipartFiles,
    AsyncMultipartFileTuple,
    BinaryFile,
    BodyChunk,
    SyncByteStream,
    SyncByteStreamFactory,
    SyncMultipartFileContent,
    SyncMultipartFiles,
    SyncMultipartFileTuple,
)


class SyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        return iter(self._chunks)


class AsyncChunks:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def sync_chunks() -> SyncByteStream:
    return SyncChunks((b"sync",))


def async_chunks() -> AsyncByteStream:
    return AsyncChunks((b"async",))


async def collect_chunks(stream: AsyncByteStream) -> list[BodyChunk]:
    return [chunk async for chunk in stream]


async def test_upload_protocols_accept_structural_streams() -> None:
    sync_stream: SyncByteStream = SyncChunks((b"one", b"two"))
    async_stream: AsyncByteStream = AsyncChunks((b"one", b"two"))

    assert list(sync_stream) == [b"one", b"two"]
    assert await collect_chunks(async_stream) == [b"one", b"two"]


def test_upload_factories_describe_replayable_stream_sources() -> None:
    sync_factory: SyncByteStreamFactory = sync_chunks
    async_factory: AsyncByteStreamFactory = async_chunks

    assert list(sync_factory()) == [b"sync"]
    assert async_factory() is not async_factory()


def test_binary_file_contract_accepts_stdlib_file_objects(tmp_path: Path) -> None:
    memory_file: BinaryFile = BytesIO(b"payload")
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"payload")

    with file_path.open("rb") as opened_file:
        disk_file: BinaryFile = opened_file
        assert disk_file.read(4) == b"payl"

    assert memory_file.read(4) == b"payl"
    assert_type(memory_file, BinaryFile)


def test_sync_multipart_file_aliases_accept_sync_sources() -> None:
    file_obj: BinaryFile = BytesIO(b"payload")
    file_content: SyncMultipartFileContent = file_obj
    file_tuple: SyncMultipartFileTuple = (
        "payload.bin",
        file_content,
        "application/octet-stream",
    )
    file_mapping = {"file": file_tuple, "stream": sync_chunks}
    files: SyncMultipartFiles = file_mapping

    assert files == file_mapping
    assert file_mapping["file"] == file_tuple
    assert file_mapping["stream"] is sync_chunks


def test_async_multipart_file_aliases_accept_async_sources() -> None:
    file_content: AsyncMultipartFileContent = async_chunks
    file_tuple: AsyncMultipartFileTuple = (
        "payload.bin",
        file_content,
        "application/octet-stream",
    )
    file_pairs = (("file", file_tuple),)
    files: AsyncMultipartFiles = file_pairs

    assert files == file_pairs
    assert file_pairs[0][1] == file_tuple


def test_async_multipart_file_aliases_accept_sync_sources() -> None:
    file_content: AsyncMultipartFileContent = sync_chunks
    file_mapping = {"file": ("payload.bin", file_content)}
    files: AsyncMultipartFiles = file_mapping

    assert files == file_mapping


def test_stream_contract_rejects_text_and_raw_buffers() -> None:
    text_stream: SyncByteStream = "payload"  # type: ignore[assignment]
    bytes_stream: SyncByteStream = b"payload"  # type: ignore[assignment]
    bytearray_stream: SyncByteStream = bytearray(b"payload")  # type: ignore[assignment]

    assert text_stream != bytes_stream
    assert bytearray_stream


def test_upload_types_are_public_reexports() -> None:
    assert foghttp_types.SyncByteStream is SyncByteStream
    assert foghttp_types.AsyncByteStream is AsyncByteStream
    assert foghttp_types.SyncByteStreamFactory is SyncByteStreamFactory
    assert foghttp_types.AsyncByteStreamFactory is AsyncByteStreamFactory
    assert foghttp_types.BinaryFile is BinaryFile
    assert foghttp_types.SyncMultipartFiles is not None
    assert foghttp_types.AsyncMultipartFiles is not None
