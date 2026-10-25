from collections.abc import AsyncIterator, Iterator

import pytest

import foghttp
from foghttp._upload_body import feeders
from tests.client_upload.upload_segmentation_cases import (
    SEGMENTATION_PAYLOAD,
    AsyncSnapshotGate,
    MutableUploadChunk,
    SyncSnapshotGate,
)


@pytest.fixture
def segmentation_limits() -> foghttp.Limits:
    return foghttp.Limits(max_upload_buffer_bytes=1024, max_total_upload_buffer_bytes=2048)


@pytest.fixture(params=("bytearray", "memoryview"))
def mutable_upload_chunk(request: pytest.FixtureRequest) -> MutableUploadChunk:
    backing = bytearray(SEGMENTATION_PAYLOAD)
    chunk = memoryview(backing) if request.param == "memoryview" else backing
    return MutableUploadChunk(backing, chunk)


@pytest.fixture
def sync_upload_snapshot(monkeypatch: pytest.MonkeyPatch) -> Iterator[SyncSnapshotGate]:
    gate = SyncSnapshotGate(SEGMENTATION_PAYLOAD)
    original = feeders.sync_body_chunks

    def gated_chunks(source: object, content_length: int | None) -> Iterator[tuple[bytes, bool]]:
        for chunk, final in original(source, content_length):
            gate.hold(chunk)
            yield chunk, final

    monkeypatch.setattr(feeders, "sync_body_chunks", gated_chunks)
    try:
        yield gate
    finally:
        gate.release.set()


@pytest.fixture
def async_upload_snapshot(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncSnapshotGate]:
    gate = AsyncSnapshotGate(SEGMENTATION_PAYLOAD)
    original = feeders.async_body_chunks

    async def gated_chunks(source: object, content_length: int | None) -> AsyncIterator[tuple[bytes, bool]]:
        async for chunk, final in original(source, content_length):
            await gate.hold(chunk)
            yield chunk, final

    monkeypatch.setattr(feeders, "async_body_chunks", gated_chunks)
    try:
        yield gate
    finally:
        gate.release.set()
