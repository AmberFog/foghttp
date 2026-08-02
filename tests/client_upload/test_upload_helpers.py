from __future__ import annotations

import asyncio
import io
import threading
from typing import TYPE_CHECKING, Any

import pytest

from foghttp._upload_body.async_sending import (
    fail_async_upload_body,
    send_async_upload_chunk,
)
import foghttp._upload_body.cleanup as upload_cleanup
from foghttp._upload_body.feeders import feed_async_upload_body, feed_sync_upload_body
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
    from collections.abc import Iterator
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
    async def feed_body(
        _raw_body: object,
        _source: object,
        _source_cleanup: object,
        _ready: asyncio.Event,
    ) -> None: ...

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

    body.raw_body.start_callback(body.raw_body)
    await body.aclose()

    assert sources
    assert sources[0].close_calls == 1
    assert body.raw_body.closed is True


def test_sync_cleanup_bridge_bounds_async_source_close(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _BlockingAsyncClose()
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)

    source_cleanup.aclose_from_sync()

    assert source.started.wait(1.0)
    assert source.finished.is_set() is False
    source_cleanup.aclose_from_sync()
    source.release.set()
    assert source.finished.wait(1.0)
    assert source.close_calls == 1


async def test_async_cleanup_survives_waiter_cancellation() -> None:
    source = _BlockingAsyncClose()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    first_waiter = asyncio.create_task(source_cleanup.aclose())
    assert await asyncio.to_thread(source.started.wait, 1.0)

    first_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_waiter

    assert source.finished.is_set() is False
    second_waiter = asyncio.create_task(source_cleanup.aclose())
    source.release.set()
    await asyncio.wait_for(second_waiter, timeout=1.0)
    assert source.finished.is_set() is True
    assert source.close_calls == 1


async def test_async_cleanup_bounds_stalled_source_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingAsyncClose()
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)

    await asyncio.wait_for(source_cleanup.aclose(), timeout=1.0)

    assert source.started.is_set() is True
    assert source.finished.is_set() is False
    source.release.set()
    await asyncio.wait_for(source_cleanup.aclose(), timeout=1.0)
    assert source.finished.is_set() is True
    assert source.close_calls == 1


async def test_async_cleanup_suppresses_source_cancelled_error() -> None:
    source = _CancelledAsyncClose()

    await upload_cleanup.UploadSourceCleanup(source).aclose()

    assert source.close_calls == 1


async def test_async_body_repeated_cancellation_still_starts_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingAsyncClose()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    drain_started = asyncio.Event()

    async def stalled_drain() -> None:
        drain_started.set()
        await asyncio.Event().wait()

    body._drain_futures = stalled_drain  # noqa: SLF001
    close_task = asyncio.create_task(body.aclose())
    await drain_started.wait()
    close_task.cancel()
    assert await asyncio.to_thread(source.started.wait, 1.0)
    close_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await close_task

    source.release.set()
    assert await asyncio.to_thread(source.finished.wait, 1.0)
    assert source.close_calls == 1


def test_sync_feeder_reports_source_cancelled_error() -> None:
    source = _CancelledSyncSource()
    raw_body = _RecordingSyncRawBody()

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
    )

    assert raw_body.failures == ["CancelledError"]
    assert source.close_calls == 1


async def test_async_feeder_reports_source_cancelled_error() -> None:
    source = _CancelledAsyncSource()
    raw_body = RetryingAsyncRawBody(fail_results=[True])

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
    )

    assert raw_body.failures == ["CancelledError"]
    assert source.close_calls == 1


async def test_async_sync_source_cancellation_closes_off_event_loop() -> None:
    source = _BlockingSyncClose()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    raw_body: Any = object()
    task = asyncio.create_task(
        feed_async_upload_body(raw_body, source, source_cleanup, asyncio.Event()),
    )
    assert await asyncio.to_thread(source.iteration_started.wait, 1.0)
    loop = asyncio.get_running_loop()
    heartbeat = threading.Event()
    responsive: list[bool] = []

    def probe_event_loop() -> None:
        if not source.close_started.wait(1.0):
            responsive.append(False)
        else:
            loop.call_soon_threadsafe(heartbeat.set)
            responsive.append(heartbeat.wait(1.0))
        source.close_release.set()

    probe = threading.Thread(target=probe_event_loop, daemon=True)
    probe.start()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)
    await asyncio.to_thread(probe.join, 1.0)

    assert responsive == [True]
    assert source.close_thread_id != threading.get_ident()
    assert source.close_finished.wait(1.0)
    assert source.close_calls == 1


async def test_async_upload_ready_notification_ignores_loop_close_race() -> None:
    source = AsyncChunks((b"payload",))
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    body._loop = _ClosingLoop()  # noqa: SLF001

    body._notify_ready()  # noqa: SLF001
    await body.aclose()

    assert source.close_calls == 1


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


class _BlockingAsyncClose:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        self.finished.set()


class _CancelledAsyncClose:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        raise asyncio.CancelledError


class _CancelledSyncSource:
    def __init__(self) -> None:
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        raise asyncio.CancelledError

    def close(self) -> None:
        self.close_calls += 1


class _CancelledAsyncSource(_CancelledAsyncClose):
    def __aiter__(self) -> _CancelledAsyncSource:
        return self

    async def __anext__(self) -> bytes:
        raise asyncio.CancelledError


class _RecordingSyncRawBody:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)


class _BlockingSyncClose:
    def __init__(self) -> None:
        self.iteration_started = threading.Event()
        self.iteration_release = threading.Event()
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.close_finished = threading.Event()
        self.close_calls = 0
        self.close_thread_id: int | None = None

    def __iter__(self) -> Iterator[bytes]:
        self.iteration_started.set()
        self.iteration_release.wait()
        yield b"payload"

    def close(self) -> None:
        self.close_calls += 1
        self.close_thread_id = threading.get_ident()
        self.close_started.set()
        self.iteration_release.set()
        self.close_release.wait()
        self.close_finished.set()


class _ClosingLoop:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, _callback: object) -> None:
        raise RuntimeError
