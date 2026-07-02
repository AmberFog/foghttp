from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import pytest

from foghttp._upload_body.async_sending import (
    fail_async_upload_body,
    send_async_upload_chunk,
)
from foghttp._upload_body.file_source import FileUploadSource, file_content_length
import foghttp._upload_body.runtime as upload_runtime
from foghttp._upload_body.thread_bridge import run_sync_upload_feeder
from tests.client_multipart.sources import AsyncChunks
from tests.client_upload.helpers import (
    FailingFilenoSeekableFile,
    FailingSeekFile,
    FailingTellFile,
    FilenoOnly,
    OversizedTellFile,
    ReadOnlyFile,
    RecordingRawUploadBody,
    RetryingAsyncRawBody,
)


if TYPE_CHECKING:
    from pathlib import Path


REGULAR_FILE_REMAINING_LENGTH = 4
SEEKABLE_FALLBACK_REMAINING_LENGTH = 5
UPLOAD_SOURCE_FAILURE = "upload source failed"


async def test_send_async_upload_chunk_waits_for_ready_signal() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[False, True])
    ready = asyncio.Event()

    task = asyncio.create_task(send_async_upload_chunk(raw_body, ready, b"payload"))
    await asyncio.sleep(0)
    ready.set()

    assert await task is True
    assert raw_body.sent_chunks == [b"payload", b"payload"]


async def test_send_async_upload_chunk_stops_when_body_is_closed() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[False], closed=True)

    assert await send_async_upload_chunk(raw_body, asyncio.Event(), b"payload") is False
    assert raw_body.sent_chunks == [b"payload"]


async def test_fail_async_upload_body_waits_for_ready_signal() -> None:
    raw_body = RetryingAsyncRawBody(fail_results=[False, True])
    ready = asyncio.Event()

    task = asyncio.create_task(fail_async_upload_body(raw_body, ready, "failed"))
    await asyncio.sleep(0)
    ready.set()
    await task

    assert raw_body.failures == ["failed", "failed"]


async def test_fail_async_upload_body_stops_when_body_is_closed() -> None:
    raw_body = RetryingAsyncRawBody(fail_results=[False], closed=True)

    await fail_async_upload_body(raw_body, asyncio.Event(), "failed")

    assert raw_body.failures == ["failed"]


async def test_run_sync_upload_feeder_propagates_source_error() -> None:
    def feeder() -> None:
        raise ValueError(UPLOAD_SOURCE_FAILURE)

    with pytest.raises(ValueError, match=UPLOAD_SOURCE_FAILURE):
        await run_sync_upload_feeder(feeder, lambda: None)


async def test_async_streaming_upload_body_closes_factory_owned_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def feed_body(_raw_body: object, _source: object, _ready: asyncio.Event) -> None: ...

    sources: list[AsyncChunks] = []

    def source_factory() -> AsyncChunks:
        source = AsyncChunks((b"payload",))
        sources.append(source)
        return source

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(upload_runtime, "feed_async_upload_body", feed_body)

    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(
            source_factory,
            content_length=None,
        ),
    )

    body.raw_body.start_callback()
    await body.aclose()

    assert sources
    assert sources[0].closed is True
    assert body.raw_body.closed is True


def test_file_upload_source_stops_on_empty_read() -> None:
    assert list(FileUploadSource(io.BytesIO())) == []


def test_file_content_length_uses_regular_file_descriptor(tmp_path: Path) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"payload")

    with file_path.open("rb") as file:
        file.read(3)

        assert file_content_length(file) == REGULAR_FILE_REMAINING_LENGTH


def test_file_content_length_rejects_regular_descriptor_without_tell(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"payload")

    with file_path.open("rb") as file:
        assert file_content_length(FilenoOnly(file.fileno())) is None


def test_file_content_length_rejects_regular_descriptor_when_tell_fails(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"payload")

    with file_path.open("rb") as file:
        assert file_content_length(FailingTellFile(file.fileno())) is None


def test_file_content_length_rejects_negative_regular_descriptor_remaining_size(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "payload.bin"
    file_path.write_bytes(b"payload")

    with file_path.open("rb") as file:
        assert file_content_length(OversizedTellFile(file.fileno())) is None


def test_file_content_length_falls_back_when_fileno_fails() -> None:
    file = FailingFilenoSeekableFile(b"payload")
    file.read(2)

    assert file_content_length(file) == SEEKABLE_FALLBACK_REMAINING_LENGTH


def test_file_content_length_returns_none_for_non_seekable_without_fileno() -> None:
    assert file_content_length(ReadOnlyFile()) is None


def test_file_content_length_returns_none_when_seek_fails() -> None:
    assert file_content_length(FailingSeekFile()) is None
