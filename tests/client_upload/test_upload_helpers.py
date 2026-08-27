from __future__ import annotations

import asyncio
from concurrent.futures import Future
import contextlib
from contextvars import ContextVar
import gc
import io
import threading
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock
import weakref

import pytest

from foghttp import _foghttp
from foghttp._upload_body.async_sending import (
    fail_async_upload_body,
    handle_async_upload_error,
    send_async_upload_chunk,
    suppress_async_cleanup_error,
)
from foghttp._upload_body.chunks import async_body_chunks, sync_body_chunks
import foghttp._upload_body.cleanup as upload_cleanup
from foghttp._upload_body.feeders import feed_async_upload_body, feed_sync_upload_body
from foghttp._upload_body.file_source import FileUploadSource, file_content_length
import foghttp._upload_body.runtime as upload_runtime
from foghttp._upload_body.thread_bridge import (
    UploadFeederState,
    consume_future_exception,
    run_daemon_callbacks_bounded,
    run_sync_in_daemon,
    run_sync_upload_feeder,
)
from tests.client_multipart.sources import AsyncChunks, BlockingSyncChunks, SyncChunks
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
    from collections.abc import Callable, Iterator
    from pathlib import Path

    AsyncFeeder = tuple[Future[None], UploadFeederState]


REGULAR_FILE_REMAINING_LENGTH = 4
SEEKABLE_FALLBACK_REMAINING_LENGTH = 5
UPLOAD_SOURCE_FAILURE = "upload source failed"
SECONDARY_CLEANUP_FAILURE = "source cleanup failed"
ERROR_FORMATTING_FAILURE = "error formatting failed"
CONCURRENT_SOURCE_CLOSE = "source closed while iteration was active"
EXPECTED_CLEANUP_CALLS = 1
EXPECTED_FAIL_CLOSED_CALLS = 2
RUNNER_START_FAILURE = "event loop is closed"


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


async def test_send_async_upload_chunk_marks_final_chunk_atomically() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[True])

    assert (
        await send_async_upload_chunk(
            raw_body,
            asyncio.Event(),
            b"payload",
            final=True,
        )
        is True
    )
    assert raw_body.sent_chunks == []
    assert raw_body.final_chunks == [b"payload"]


async def test_send_async_empty_upload_chunk_yields_and_observes_close() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[True], closed=True)
    loop_progressed = asyncio.Event()
    asyncio.get_running_loop().call_soon(loop_progressed.set)

    sent = await send_async_upload_chunk(raw_body, asyncio.Event(), b"")

    assert sent is False
    assert loop_progressed.is_set()


async def test_send_async_empty_final_chunk_reports_terminal_success() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[True], closed=True)

    sent = await send_async_upload_chunk(
        raw_body,
        asyncio.Event(),
        b"",
        final=True,
    )

    assert sent is True
    assert raw_body.final_chunks == [b""]


async def test_send_async_empty_final_chunk_rejects_closed_body() -> None:
    raw_body = RetryingAsyncRawBody(send_results=[False], closed=True)

    sent = await send_async_upload_chunk(
        raw_body,
        asyncio.Event(),
        b"",
        final=True,
    )

    assert sent is False
    assert raw_body.final_chunks == [b""]


def test_closed_raw_upload_body_rejects_empty_chunks() -> None:
    raw_body = _foghttp.RawUploadBody(
        None,
        lambda _body: None,
        replayable=False,
        ready_callback=None,
    )
    raw_body.close()

    assert raw_body.send(b"") is False
    assert raw_body.send_nowait(b"") is False


def test_raw_upload_body_accepts_each_empty_final_chunk_only_once() -> None:
    blocking_body = _foghttp.RawUploadBody(
        None,
        lambda _body: None,
        replayable=False,
        ready_callback=None,
    )
    nonblocking_body = _foghttp.RawUploadBody(
        None,
        lambda _body: None,
        replayable=False,
        ready_callback=None,
    )

    assert blocking_body.send_final(b"") is True
    assert blocking_body.send_final(b"") is False
    assert nonblocking_body.send_final_nowait(b"") is True
    assert nonblocking_body.send_final_nowait(b"") is False


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


async def test_async_upload_error_preserves_failure_reporting_control_error() -> None:
    report_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    raw_body = RetryingAsyncRawBody()
    raw_body.fail_nowait = Mock(side_effect=report_error)

    result = await handle_async_upload_error(
        raw_body,
        asyncio.Event(),
        ValueError(UPLOAD_SOURCE_FAILURE),
        task_is_cancelling=False,
    )

    assert result is report_error


async def test_async_cleanup_suppresses_non_cancellation_error() -> None:
    async def fail_cleanup() -> None:
        raise RuntimeError(SECONDARY_CLEANUP_FAILURE)

    await suppress_async_cleanup_error(fail_cleanup())


def test_exact_length_chunk_helpers_stop_after_terminal_chunk() -> None:
    assert list(sync_body_chunks((b"x", b"ignored"), 1)) == [(b"x", True)]


async def test_async_chunk_helper_handles_zero_and_exact_lengths() -> None:
    assert [chunk async for chunk in async_body_chunks(AsyncChunks((b"ignored",)), 0)] == []
    assert [chunk async for chunk in async_body_chunks(AsyncChunks((b"x", b"ignored")), 1)] == [
        (b"x", True),
    ]


async def test_run_sync_upload_feeder_propagates_source_error() -> None:
    def feeder() -> None:
        raise ValueError(UPLOAD_SOURCE_FAILURE)

    with pytest.raises(ValueError, match=UPLOAD_SOURCE_FAILURE):
        await run_sync_upload_feeder(feeder, lambda: None)


async def test_run_sync_upload_feeder_propagates_control_error() -> None:
    def feeder() -> None:
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        await run_sync_upload_feeder(feeder, lambda: None)


async def test_sync_feeder_translates_control_error_after_handled_cancellation() -> None:
    cancel = Mock()

    def feeder() -> None:
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    async def cancelled_owner() -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0)
        await run_sync_upload_feeder(feeder, cancel)

    task = asyncio.create_task(cancelled_owner())
    with pytest.raises(asyncio.CancelledError):
        await task

    cancel.assert_called_once_with()


async def test_cancelled_sync_daemon_consumes_late_control_error() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    worker_state = UploadFeederState()

    def callback() -> None:
        started.set()
        release.wait()
        finished.set()
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    task = asyncio.create_task(run_sync_in_daemon(callback, worker_state=worker_state))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker_state.worker_pending() is True
    release.set()

    assert await asyncio.to_thread(finished.wait, 1.0)
    for _attempt in range(10):
        if not worker_state.worker_pending():
            break
        await asyncio.sleep(0)
    assert worker_state.worker_pending() is False
    await asyncio.sleep(0)


async def test_sync_daemon_preserves_context_off_event_loop() -> None:
    request_context: ContextVar[str] = ContextVar("request_context")
    request_context.set("request-value")
    event_loop_thread_id = threading.get_ident()

    worker_thread_id, observed_context = await run_sync_in_daemon(
        lambda: (threading.get_ident(), request_context.get()),
    )

    assert worker_thread_id != event_loop_thread_id
    assert observed_context == "request-value"


def test_future_exception_consumer_suppresses_callback_control_error() -> None:
    completion: Future[None] = Future()
    completion.set_result(None)
    callback = Mock(side_effect=GeneratorExit(SECONDARY_CLEANUP_FAILURE))

    assert consume_future_exception(completion, callback=callback) is None
    callback.assert_called_once_with()


async def test_cancelled_sync_feeder_consumes_late_control_error() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def feeder() -> None:
        started.set()
        release.wait()
        finished.set()
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    task = asyncio.create_task(run_sync_upload_feeder(feeder, lambda: None))
    assert await asyncio.to_thread(started.wait, 1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()

    assert await asyncio.to_thread(finished.wait, 1.0)
    await asyncio.sleep(0)


async def test_async_streaming_upload_body_closes_factory_owned_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def feed_body(
        _raw_body: object,
        _source: object,
        _source_cleanup: object,
        _ready: asyncio.Event,
        _feeder_state: UploadFeederState,
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

    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    await body.aclose()

    assert sources
    assert sources[0].close_calls == 1
    assert raw_body.closed is True
    assert body.raw_body is None


def test_sync_streaming_body_preserves_request_context_for_each_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("sync_upload_request_context")
    request_context.set("request")
    observations: list[tuple[str, int, str]] = []
    finished = (threading.Event(), threading.Event())
    factory_calls = 0

    def source_factory() -> tuple[int]:
        nonlocal factory_calls
        attempt = factory_calls
        factory_calls += 1
        observations.append(("factory", attempt, request_context.get()))
        request_context.set(f"factory-{attempt}")
        return (attempt,)

    def feed_body(
        _raw_body: object,
        source: object,
        source_cleanup: upload_cleanup.UploadSourceCleanup,
        _feeder_state: UploadFeederState,
    ) -> None:
        attempt = cast("tuple[int]", source)[0]
        observations.append(("feeder", attempt, request_context.get()))
        source_cleanup.close()
        finished[attempt].set()

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(upload_runtime, "feed_sync_upload_body", feed_body)
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    raw_body.start_callback(raw_body)
    assert finished[0].wait(1.0)
    raw_body.start_callback(raw_body)
    assert finished[1].wait(1.0)
    body.close()

    assert observations == [
        ("factory", 0, "request"),
        ("feeder", 0, "factory-0"),
        ("factory", 1, "request"),
        ("feeder", 1, "factory-1"),
    ]


def test_sync_streaming_body_rejects_factory_result_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_started = threading.Event()
    factory_release = threading.Event()
    source = BlockingSyncChunks((b"payload",))

    def source_factory() -> BlockingSyncChunks:
        factory_started.set()
        factory_release.wait()
        return source

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    starter = threading.Thread(
        target=raw_body.start_callback,
        args=(raw_body,),
        daemon=True,
    )
    starter.start()
    assert factory_started.wait(1.0)

    body.close()
    factory_release.set()
    starter.join(timeout=1.0)

    assert starter.is_alive() is False
    assert source.release.wait(1.0)
    assert source.started.is_set() is False
    assert source.close_calls == 1
    assert raw_body.closed is True


def test_sync_streaming_factory_cleans_async_source_in_attempt_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("rejected_source_context")
    request_context.set("request")
    observations: list[str] = []
    source = _ContextRecordingAsyncClose(request_context, observations)

    def source_factory() -> _ContextRecordingAsyncClose:
        request_context.set("factory")
        return source

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(TypeError):
        raw_body.start_callback(raw_body)
    body.close()

    assert observations == ["factory"]


def test_sync_streaming_factory_classifies_source_in_attempt_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("classified_source_context")
    request_context.set("request")
    observations: list[tuple[str, str]] = []
    source = _ContextClassifiedAsyncClose(request_context, observations)

    def source_factory() -> _ContextClassifiedAsyncClose:
        request_context.set("factory")
        return source

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(TypeError):
        raw_body.start_callback(raw_body)
    body.close()

    assert observations == [("classify", "factory"), ("close", "factory")]


def test_sync_streaming_factory_preserves_async_source_type_error_when_cleanup_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks(())
    real_start = threading.Thread.start

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(lambda: source),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(TypeError, match="sync Client cannot send async"):
        raw_body.start_callback(raw_body)
    monkeypatch.setattr(threading.Thread, "start", real_start)
    body.close()

    assert source.close_calls == 1


async def test_async_streaming_body_preserves_request_context_for_each_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("async_upload_request_context")
    request_context.set("request")
    observations: list[tuple[str, int, str]] = []
    finished = (asyncio.Event(), asyncio.Event())
    factory_calls = 0

    def source_factory() -> tuple[int]:
        nonlocal factory_calls
        attempt = factory_calls
        factory_calls += 1
        observations.append(("factory", attempt, request_context.get()))
        request_context.set(f"factory-{attempt}")
        return (attempt,)

    async def feed_body(
        _raw_body: object,
        source: object,
        source_cleanup: upload_cleanup.UploadSourceCleanup,
        _ready: asyncio.Event,
        _feeder_state: UploadFeederState,
    ) -> None:
        attempt = cast("tuple[int]", source)[0]
        observations.append(("feeder", attempt, request_context.get()))
        await source_cleanup.aclose()
        finished[attempt].set()

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(upload_runtime, "feed_async_upload_body", feed_body)
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    raw_body.start_callback(raw_body)
    await asyncio.wait_for(finished[0].wait(), timeout=1.0)
    raw_body.start_callback(raw_body)
    await asyncio.wait_for(finished[1].wait(), timeout=1.0)
    await body.aclose()

    assert observations == [
        ("factory", 0, "request"),
        ("feeder", 0, "factory-0"),
        ("factory", 1, "request"),
        ("feeder", 1, "factory-1"),
    ]


async def test_async_streaming_body_rejects_late_start_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(AsyncChunks(())),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    await body.aclose()
    raw_body.start_callback(raw_body)

    assert raw_body.closed is True


async def test_async_streaming_body_does_not_call_replay_factory_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_factory = Mock(return_value=AsyncChunks(()))
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    await body.aclose()
    raw_body.start_callback(raw_body)

    source_factory.assert_not_called()
    assert raw_body.closed is True


async def test_async_streaming_body_preserves_factory_error_over_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_error = RuntimeError(UPLOAD_SOURCE_FAILURE)
    cleanup_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    source = _SeparateAsyncIteratorSource([], source_close_error=cleanup_error)

    def source_factory() -> upload_cleanup.UploadSourceFactoryFailure:
        return upload_cleanup.UploadSourceFactoryFailure(source, factory_error)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    async def start_and_close() -> None:
        try:
            raw_body.start_callback(raw_body)
        finally:
            await body.aclose()

    with pytest.raises(RuntimeError) as exc_info:
        await start_and_close()

    assert exc_info.value is factory_error
    assert exc_info.value.__cause__ is cleanup_error
    assert source.close_calls == 1


def test_sync_streaming_body_preserves_factory_error_over_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_error = RuntimeError(UPLOAD_SOURCE_FAILURE)
    cleanup_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    source = _SeparateSyncIteratorSource([], source_close_error=cleanup_error)

    def source_factory() -> upload_cleanup.UploadSourceFactoryFailure:
        return upload_cleanup.UploadSourceFactoryFailure(source, factory_error)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError) as exc_info:
        raw_body.start_callback(raw_body)

    assert exc_info.value is factory_error
    assert exc_info.value.__cause__ is cleanup_error
    assert source.close_calls == 1
    body.close()


def test_sync_streaming_body_releases_raw_callback_cycle() -> None:
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(()),
    )
    body_ref = weakref.ref(body)

    body.close()
    assert body.raw_body is None
    body.close()
    del body

    assert body_ref() is None


async def test_async_streaming_body_releases_raw_callback_cycle() -> None:
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(AsyncChunks(())),
    )
    body_ref = weakref.ref(body)

    await body.aclose()
    assert body.raw_body is None
    await body.aclose()
    del body

    assert body_ref() is None


async def test_async_streaming_body_releases_raw_callback_cycle_after_cleanup_error() -> None:
    source_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source = _SeparateAsyncIteratorSource([], source_close_error=source_error)
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    body_ref = weakref.ref(body)

    with pytest.raises(GeneratorExit) as exc_info:
        await body.aclose()
    assert exc_info.value is source_error
    del exc_info
    del body
    del source
    del source_error
    await asyncio.sleep(0)
    gc.collect()

    assert body_ref() is None


def test_sync_streaming_body_propagates_feeder_cleanup_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source = _SeparateSyncIteratorSource([], source_close_error=source_error)
    raw_body = Mock()
    raw_body.send.return_value = True

    def raw_body_factory(
        _content_length: int | None,
        start_callback: object,
        _replayable: object,
        _ready_callback: object,
    ) -> Mock:
        raw_body.start_callback = start_callback
        return raw_body

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        raw_body_factory,
    )
    body: Any = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    body.raw_body.start_callback(body.raw_body)
    assert source.close_started.wait(1.0)

    with pytest.raises(GeneratorExit) as exc_info:
        body.close()

    assert exc_info.value is source_error
    assert raw_body.close.call_count == EXPECTED_FAIL_CLOSED_CALLS
    assert body.raw_body is None


async def test_async_streaming_body_propagates_feeder_cleanup_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source = _SeparateAsyncIteratorSource([], source_close_error=source_error)
    raw_body = Mock()
    raw_body.send_nowait.return_value = True

    def raw_body_factory(
        _content_length: int | None,
        start_callback: object,
        _replayable: object,
        _ready_callback: object,
    ) -> Mock:
        raw_body.start_callback = start_callback
        return raw_body

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        raw_body_factory,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    body.raw_body.start_callback(body.raw_body)
    with pytest.raises(GeneratorExit):
        await asyncio.wrap_future(_async_body_feeders(body)[0][0])

    with pytest.raises(GeneratorExit) as exc_info:
        await body.aclose()

    assert exc_info.value is source_error
    assert raw_body.close.call_count == EXPECTED_FAIL_CLOSED_CALLS
    assert body.raw_body is None


def test_sync_streaming_body_observes_control_error_before_cleanup_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingControlSyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    assert source.close_started.wait(1.0)

    try:
        with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
            body.close()
    finally:
        source.close_release.set()

    assert source.close_finished.wait(1.0)
    assert source.close_calls == 1


async def test_async_streaming_body_observes_sync_control_error_before_cleanup_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingControlSyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    assert await asyncio.to_thread(source.close_started.wait, 1.0)

    try:
        with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
            await body.aclose()
    finally:
        source.close_release.set()

    assert await asyncio.to_thread(source.close_finished.wait, 1.0)
    assert source.close_calls == 1


async def test_async_streaming_body_close_wins_over_late_sync_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _CancellationControlSyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    assert await asyncio.to_thread(source.iteration_started.wait, 1.0)

    await body.aclose()

    assert source.close_finished.wait(1.0)
    assert source.close_calls == 1
    assert body.raw_body is None


async def test_async_streaming_body_cancellation_wins_over_saved_control_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(AsyncChunks(())),
    )
    _set_async_body_feeder_error(body, GeneratorExit(UPLOAD_SOURCE_FAILURE))
    started = asyncio.Event()

    async def cancelled_owner() -> None:
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await body.aclose()

    task = asyncio.create_task(cancelled_owner())
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert body.raw_body is None


async def test_async_streaming_body_reports_saved_error_after_handled_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(AsyncChunks(())),
    )
    feeder_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    _set_async_body_feeder_error(body, feeder_error)
    started = asyncio.Event()

    async def cancelled_owner() -> None:
        started.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()
        await body.aclose()

    task = asyncio.create_task(cancelled_owner())
    await started.wait()

    task.cancel()
    with pytest.raises(GeneratorExit) as exc_info:
        await task

    assert exc_info.value is feeder_error


def _set_async_body_feeder_error(body: Any, error: BaseException) -> None:
    feeder_error_state = UploadFeederState()
    feeder_error_state.publish(error)
    feeder_future: Future[None] = Future()
    feeder_future.set_result(None)
    _set_async_body_feeders(body, [(feeder_future, feeder_error_state)])


def _set_async_body_feeders(
    body: Any,
    feeders: list[AsyncFeeder],
) -> None:
    source_cleanup = body._source_cleanups[0]  # noqa: SLF001
    body._feeders = []  # noqa: SLF001
    for future, state in feeders:
        runner = Mock(completion=future)
        runner.cancel.side_effect = future.cancel
        body._feeders.append((runner, state, source_cleanup))  # noqa: SLF001


def _async_body_feeders(body: Any) -> list[AsyncFeeder]:
    return [
        (runner.completion, state)
        for runner, state, _source_cleanup in body._feeders  # noqa: SLF001
    ]


async def _drain_async_body_feeders(body: Any) -> BaseException | None:
    return await body._drain_futures()  # noqa: SLF001


def _notify_async_body(body: Any, loop: object) -> None:
    body._loop = loop  # noqa: SLF001
    body._notify_ready()  # noqa: SLF001


def test_sync_streaming_body_prefers_feeder_error_over_source_cleanup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_source() -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(empty_source),
    )
    feeder_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source_cleanup = Mock()
    source_cleanup.interrupt.side_effect = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    feeder_error_state = UploadFeederState()
    feeder_error_state.publish(feeder_error)
    body._feeder_errors, body._source_cleanups = (  # noqa: SLF001
        [feeder_error_state],
        [source_cleanup],
    )

    with pytest.raises(GeneratorExit) as exc_info:
        body.close()

    assert exc_info.value is feeder_error
    source_cleanup.interrupt.assert_called_once_with()


async def test_async_streaming_body_prefers_feeder_error_over_source_cleanup_error() -> None:
    feeder_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source = _SeparateAsyncIteratorSource(
        [],
        source_close_error=GeneratorExit(SECONDARY_CLEANUP_FAILURE),
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    feeder_future: Future[None] = Future()
    feeder_future.set_exception(feeder_error)
    _set_async_body_feeders(body, [(feeder_future, UploadFeederState())])

    with pytest.raises(GeneratorExit) as exc_info:
        await body.aclose()

    assert exc_info.value is feeder_error
    assert source.close_calls == 1


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


def test_sync_cleanup_bridge_preserves_context() -> None:
    request_context: ContextVar[str] = ContextVar("cleanup_request_context")
    request_context.set("request-value")
    observations: list[str] = []
    source = _ContextRecordingAsyncClose(request_context, observations)

    upload_cleanup.UploadSourceCleanup(source).aclose_from_sync()

    assert observations == ["request-value"]


def test_sync_cleanup_bridge_retries_after_thread_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks(())
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    real_start = threading.Thread.start

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    source_cleanup.aclose_from_sync()
    monkeypatch.setattr(threading.Thread, "start", real_start)

    source_cleanup.aclose_from_sync()

    assert source.close_calls == 1


def test_sync_cleanup_close_retries_after_thread_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks(())
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    real_start = threading.Thread.start

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    source_cleanup.close()
    monkeypatch.setattr(threading.Thread, "start", real_start)

    source_cleanup.close()

    assert source.close_calls == 1


def test_sync_cleanup_interrupt_retries_after_thread_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks(())
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    real_start = threading.Thread.start

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    source_cleanup.interrupt()
    monkeypatch.setattr(threading.Thread, "start", real_start)

    source_cleanup.interrupt()

    assert source.close_calls == 1


def test_bounded_daemon_callbacks_do_not_run_cleanup_inline_after_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback = Mock(side_effect=AssertionError)

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(threading.Thread, "start", fail_start)

    error = run_daemon_callbacks_bounded((callback,), timeout=0.01)

    assert isinstance(error, RuntimeError)
    callback.assert_not_called()


def test_sync_cleanup_suppresses_cleanup_lookup_error() -> None:
    source = _FailingCloseLookup()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)

    source_cleanup.close()
    source_cleanup.close()

    assert source.lookup_calls == 1


async def test_async_cleanup_suppresses_cleanup_lookup_error() -> None:
    source = _FailingAsyncCloseLookup()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)

    await source_cleanup.aclose()
    await source_cleanup.aclose()

    assert source.lookup_calls == 1


def test_sync_cleanup_bridge_propagates_control_error_at_most_once() -> None:
    source = _BlockingAsyncClose(error=GeneratorExit(SECONDARY_CLEANUP_FAILURE))
    source.release.set()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)

    with pytest.raises(GeneratorExit, match=SECONDARY_CLEANUP_FAILURE):
        source_cleanup.aclose_from_sync()
    source_cleanup.aclose_from_sync()

    assert source.close_calls == 1


async def test_async_cleanup_retries_after_task_factory_failure() -> None:
    source = AsyncChunks(())
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    captured_coroutines: list[Any] = []
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()

    def fail_task_factory(
        _loop: Any,
        coroutine: Any,
        **_kwargs: Any,
    ) -> Any:
        captured_coroutines.append(coroutine)
        raise RuntimeError(RUNNER_START_FAILURE)

    loop.set_task_factory(fail_task_factory)
    try:
        await source_cleanup.aclose()
    finally:
        loop.set_task_factory(previous_factory)

    assert len(captured_coroutines) == 1
    assert captured_coroutines[0].cr_frame is None
    assert source.close_calls == 0

    await source_cleanup.aclose()

    assert source.close_calls == 1


async def test_interrupt_cleanup_task_factory_failure_is_best_effort() -> None:
    source = SyncChunks(())
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    captured_coroutines: list[Any] = []
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()

    def fail_task_factory(
        _loop: Any,
        coroutine: Any,
        **_kwargs: Any,
    ) -> Any:
        captured_coroutines.append(coroutine)
        raise RuntimeError(RUNNER_START_FAILURE)

    loop.set_task_factory(fail_task_factory)
    try:
        source_cleanup.start_async_cleanup(interrupt=True)
    finally:
        loop.set_task_factory(previous_factory)

    assert len(captured_coroutines) == 1
    assert captured_coroutines[0].cr_frame is None
    source_cleanup.close()
    assert source.close_calls == 1


def test_sync_streaming_body_joins_feeders_before_cleanup_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_source() -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(empty_source),
    )
    interrupted_cleanup = Mock()
    interrupted_cleanup.interrupt.side_effect = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    remaining_cleanup = Mock()
    remaining_cleanup.interrupt.side_effect = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    feeder_thread = Mock()
    body._source_cleanups, body._threads = (  # noqa: SLF001
        [interrupted_cleanup, remaining_cleanup],
        [feeder_thread],
    )
    raw_body = body.raw_body

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        body.close()

    interrupted_cleanup.interrupt.assert_called_once_with()
    remaining_cleanup.interrupt.assert_called_once_with()
    feeder_thread.join.assert_called_once_with(upload_runtime.UPLOAD_FEEDER_JOIN_TIMEOUT)
    assert raw_body.closed is True
    assert body.raw_body is None


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


async def test_cancelled_async_cleanup_waiter_consumes_late_control_error() -> None:
    source = _BlockingAsyncClose(error=GeneratorExit(SECONDARY_CLEANUP_FAILURE))
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_exception_handler = loop.get_exception_handler()

    def capture_loop_error(
        _loop: asyncio.AbstractEventLoop,
        context: dict[str, object],
    ) -> None:
        loop_errors.append(context)

    loop.set_exception_handler(capture_loop_error)
    try:
        waiter = asyncio.create_task(source_cleanup.aclose())
        assert await asyncio.to_thread(source.started.wait, 1.0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        source.release.set()
        assert await asyncio.to_thread(source.finished.wait, 1.0)
        await asyncio.sleep(0)
    finally:
        source.release.set()
        loop.set_exception_handler(previous_exception_handler)

    assert loop_errors == []
    assert source.close_calls == EXPECTED_CLEANUP_CALLS


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


async def test_async_streaming_body_bounds_stalled_source_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingAsyncClose()
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )

    await asyncio.wait_for(body.aclose(), timeout=1.0)

    assert source.started.is_set() is True
    assert source.finished.is_set() is False
    source.release.set()
    assert await asyncio.to_thread(source.finished.wait, 1.0)
    assert source.close_calls == 1


def test_sync_streaming_body_bounds_stalled_source_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingSyncClose()
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    finished = threading.Event()

    def close_body() -> None:
        body.close()
        finished.set()

    closer = threading.Thread(target=close_body, daemon=True)
    closer.start()
    assert source.close_started.wait(1.0)
    assert finished.wait(1.0)
    assert source.close_finished.is_set() is False

    source.close_release.set()
    assert source.close_finished.wait(1.0)
    closer.join(timeout=1.0)
    assert source.close_calls == 1


def test_sync_cleanup_does_not_wait_for_stalled_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingSyncClose()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    interrupt = threading.Thread(target=source_cleanup.interrupt, daemon=True)
    close_finished = threading.Event()

    def close_source() -> None:
        source_cleanup.close()
        close_finished.set()

    interrupt.start()
    assert source.close_started.wait(1.0)
    closer = threading.Thread(target=close_source, daemon=True)
    closer.start()

    assert close_finished.wait(1.0)
    source.close_release.set()
    interrupt.join(timeout=1.0)
    closer.join(timeout=1.0)
    assert source.close_finished.is_set()
    assert source.close_calls == 1


async def test_background_async_cleanup_survives_owner_collection() -> None:
    started = asyncio.Event()
    source = _GcBlockedAsyncClose(started)
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    existing_tasks = asyncio.all_tasks()

    source_cleanup.start_async_cleanup()
    await started.wait()
    cleanup_tasks = asyncio.all_tasks() - existing_tasks
    assert len(cleanup_tasks) == 1
    cleanup_task = cleanup_tasks.pop()
    cleanup_ref = weakref.ref(cleanup_task)

    del cleanup_task
    del cleanup_tasks
    del source_cleanup
    del source
    gc.collect()

    assert cleanup_ref() is not None
    cleanup_task = cleanup_ref()
    assert cleanup_task is not None
    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task


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


async def test_pending_async_runner_starts_cleanup_after_owner_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks((b"payload",))
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(
        upload_runtime.AsyncFeederRunner,
        "start",
        lambda _runner, **_kwargs: None,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    runner_completion = _async_body_feeders(body)[0][0]

    close_task = asyncio.create_task(body.aclose())
    await asyncio.sleep(0)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert source.close_calls == 0
    runner_completion.cancel()
    for _attempt in range(10):
        if source.close_calls:
            break
        await asyncio.sleep(0)
    assert source.close_calls == EXPECTED_CLEANUP_CALLS


async def test_async_runner_start_failure_keeps_source_available_for_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks((b"payload",))

    def fail_start(_runner: object, **_kwargs: object) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(upload_runtime.AsyncFeederRunner, "start", fail_start)
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        raw_body.start_callback(raw_body)
    assert _async_body_feeders(body) == []
    await body.aclose()

    assert source.close_calls == 1


async def test_async_runner_start_failure_preserves_factory_cleanup_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("async_start_failure_context")
    request_context.set("request")
    observations: list[str] = []
    source = _ContextRecordingAsyncClose(request_context, observations)

    def source_factory() -> _ContextRecordingAsyncClose:
        request_context.set("factory")
        return source

    def fail_start(_runner: object, **_kwargs: object) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(upload_runtime.AsyncFeederRunner, "start", fail_start)
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        raw_body.start_callback(raw_body)
    await body.aclose()

    assert observations == ["factory"]


async def test_async_factory_failure_preserves_cleanup_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("async_factory_failure_context")
    request_context.set("request")
    observations: list[str] = []
    source = _ContextRecordingAsyncClose(request_context, observations)

    def source_factory() -> upload_cleanup.UploadSourceFactoryFailure:
        request_context.set("factory")
        return upload_cleanup.UploadSourceFactoryFailure(
            source,
            RuntimeError(UPLOAD_SOURCE_FAILURE),
        )

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError, match=UPLOAD_SOURCE_FAILURE):
        raw_body.start_callback(raw_body)
    await body.aclose()

    assert observations == ["factory"]


async def test_async_close_cleans_factory_source_registered_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_started = threading.Event()
    factory_release = threading.Event()
    source = AsyncChunks(())
    factory_error = RuntimeError(UPLOAD_SOURCE_FAILURE)

    def source_factory() -> upload_cleanup.UploadSourceFactoryFailure:
        factory_started.set()
        factory_release.wait()
        return upload_cleanup.UploadSourceFactoryFailure(source, factory_error)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    errors: list[BaseException] = []

    def start_body() -> None:
        try:
            raw_body.start_callback(raw_body)
        except RuntimeError as error:
            errors.append(error)

    starter = threading.Thread(target=start_body, daemon=True)
    starter.start()
    assert await asyncio.to_thread(factory_started.wait, 1.0)
    await body.aclose()
    factory_release.set()
    await asyncio.to_thread(starter.join, 1.0)
    for _attempt in range(10):
        if source.close_calls:
            break
        await asyncio.sleep(0)

    assert errors == [factory_error]
    assert source.close_calls == 1


async def test_async_sync_worker_start_failure_closes_body_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SyncChunks((b"payload",))
    real_start = threading.Thread.start
    start_calls = 0

    def fail_first_start(thread: threading.Thread) -> None:
        nonlocal start_calls
        start_calls += 1
        if start_calls == 1:
            raise RuntimeError(RUNNER_START_FAILURE)
        real_start(thread)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(threading.Thread, "start", fail_first_start)
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)

    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        await asyncio.wrap_future(_async_body_feeders(body)[0][0])
    for _attempt in range(10):
        if source.close_calls:
            break
        await asyncio.sleep(0)

    assert raw_body.closed is True
    assert source.close_calls == 1
    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        await body.aclose()


async def test_async_source_classification_failure_closes_body_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _FailingAsyncLookupSyncSource((b"payload",))
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(lambda: source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)

    with pytest.raises(RuntimeError, match=UPLOAD_SOURCE_FAILURE):
        await asyncio.wrap_future(_async_body_feeders(body)[0][0])
    for _attempt in range(10):
        if source.close_calls:
            break
        await asyncio.sleep(0)

    assert raw_body.closed is True
    assert source.close_calls == 1
    with pytest.raises(RuntimeError, match=UPLOAD_SOURCE_FAILURE):
        await body.aclose()


def test_sync_thread_start_failure_keeps_source_available_for_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SyncChunks((b"payload",))
    real_start = threading.Thread.start

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        raw_body.start_callback(raw_body)
    monkeypatch.setattr(threading.Thread, "start", real_start)
    body.close()

    assert source.close_calls == 1


def test_sync_thread_start_failure_preserves_factory_cleanup_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_context: ContextVar[str] = ContextVar("sync_start_failure_context")
    request_context.set("request")
    observations: list[str] = []
    source = _ContextRecordingSyncSource(request_context, observations)
    real_start = threading.Thread.start

    def source_factory() -> _ContextRecordingSyncSource:
        request_context.set("factory")
        return source

    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError(RUNNER_START_FAILURE)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    monkeypatch.setattr(threading.Thread, "start", fail_start)
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.replayable_streaming_body(source_factory),
    )
    request_context.set("outside")
    raw_body = body.raw_body
    assert raw_body is not None

    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        raw_body.start_callback(raw_body)
    monkeypatch.setattr(threading.Thread, "start", real_start)
    body.close()

    assert observations == ["factory"]


async def test_async_runner_closes_feeder_when_task_creation_fails() -> None:
    captured_coroutines: list[Any] = []

    async def feeder() -> None:
        return

    def fail_task_factory(
        _loop: Any,
        coroutine: Any,
        **_kwargs: Any,
    ) -> Any:
        captured_coroutines.append(coroutine)
        raise RuntimeError(RUNNER_START_FAILURE)

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    runner = upload_runtime.AsyncFeederRunner(loop, feeder)
    loop.set_task_factory(fail_task_factory)
    try:
        runner.start()
        await asyncio.sleep(0)
    finally:
        loop.set_task_factory(previous_factory)

    assert isinstance(runner.completion.exception(), RuntimeError)
    assert len(captured_coroutines) == 1
    assert captured_coroutines[0].cr_frame is None


async def test_async_runner_task_factory_failure_closes_body_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks((b"payload",))
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    factory_calls = 0

    def fail_first_task_factory(
        task_loop: asyncio.AbstractEventLoop,
        coroutine: Any,
        **kwargs: Any,
    ) -> asyncio.Future[Any]:
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            raise RuntimeError(RUNNER_START_FAILURE)
        if previous_factory is not None:
            return previous_factory(task_loop, coroutine, **kwargs)
        return asyncio.Task(coroutine, loop=task_loop, **kwargs)

    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    loop.set_task_factory(fail_first_task_factory)
    try:
        raw_body.start_callback(raw_body)
        with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
            await asyncio.wrap_future(_async_body_feeders(body)[0][0])
        for _attempt in range(10):
            if source.close_calls:
                break
            await asyncio.sleep(0)
    finally:
        loop.set_task_factory(previous_factory)

    assert raw_body.closed is True
    assert source.close_calls == 1
    with pytest.raises(RuntimeError, match=RUNNER_START_FAILURE):
        await body.aclose()


def test_sync_feeder_reports_source_cancelled_error() -> None:
    source = _FailingSyncSource(asyncio.CancelledError())
    raw_body = _RecordingSyncRawBody()

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        UploadFeederState(),
    )

    assert raw_body.failures == ["CancelledError"]
    assert source.close_calls == 1


def test_sync_feeder_reports_terminal_send_error() -> None:
    raw_body = _RecordingSyncRawBody()
    raw_body.finish = Mock(side_effect=ValueError(UPLOAD_SOURCE_FAILURE))

    feed_sync_upload_body(
        raw_body,
        (),
        upload_cleanup.UploadSourceCleanup(()),
        UploadFeederState(),
    )

    assert raw_body.failures == [UPLOAD_SOURCE_FAILURE]


def test_sync_feeder_propagates_terminal_send_control_error() -> None:
    terminal_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    raw_body = _RecordingSyncRawBody()
    raw_body.finish = Mock(side_effect=terminal_error)

    with pytest.raises(GeneratorExit) as exc_info:
        feed_sync_upload_body(
            raw_body,
            (),
            upload_cleanup.UploadSourceCleanup(()),
            UploadFeederState(),
        )

    assert exc_info.value is terminal_error
    assert raw_body.closed is True


def test_sync_feeder_propagates_failure_reporting_control_error() -> None:
    report_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    source = _FailingSyncSource(ValueError(UPLOAD_SOURCE_FAILURE))
    raw_body = _RecordingSyncRawBody()
    raw_body.fail = Mock(side_effect=report_error)

    with pytest.raises(GeneratorExit) as exc_info:
        feed_sync_upload_body(
            raw_body,
            source,
            upload_cleanup.UploadSourceCleanup(source),
            UploadFeederState(),
        )

    assert exc_info.value is report_error
    assert raw_body.closed is True


def test_cancelled_sync_feeder_suppresses_source_error_report() -> None:
    source = _FailingSyncSource(ValueError(UPLOAD_SOURCE_FAILURE))
    raw_body = _RecordingSyncRawBody()
    feeder_state = UploadFeederState()
    feeder_state.cancel()

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        feeder_state,
    )

    assert raw_body.failures == []
    assert source.close_calls == 1


def test_cancelled_empty_sync_feeder_does_not_finish_body() -> None:
    raw_body = _RecordingSyncRawBody()
    feeder_state = UploadFeederState()
    feeder_state.cancel()

    feed_sync_upload_body(
        raw_body,
        (),
        upload_cleanup.UploadSourceCleanup(()),
        feeder_state,
    )

    assert raw_body.events == []


def test_sync_feeder_falls_back_when_error_formatting_fails() -> None:
    events: list[str] = []
    source = _SeparateSyncIteratorSource(
        events,
        error=_UnprintableError(),
        source_close_error=GeneratorExit(SECONDARY_CLEANUP_FAILURE),
    )
    raw_body = _RecordingSyncRawBody(events)

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        UploadFeederState(),
    )

    assert raw_body.failures == ["_UnprintableError"]
    assert raw_body.closed is False
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["fail", "iterator_close", "source_close"]


async def test_async_feeder_falls_back_when_error_formatting_fails() -> None:
    events: list[str] = []
    source = _SeparateAsyncIteratorSource(
        events,
        error=_UnprintableError(),
        source_close_error=GeneratorExit(SECONDARY_CLEANUP_FAILURE),
    )
    raw_body = RetryingAsyncRawBody(fail_results=[True], events=events)

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(),
    )

    assert raw_body.failures == ["_UnprintableError"]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["fail", "iterator_close", "source_close"]


def test_sync_feeder_preserves_reported_source_error_over_cleanup_control_error() -> None:
    events: list[str] = []
    source = _SeparateSyncIteratorSource(
        events,
        error=ValueError(UPLOAD_SOURCE_FAILURE),
        source_close_error=GeneratorExit(SECONDARY_CLEANUP_FAILURE),
    )
    raw_body = _RecordingSyncRawBody(events)

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        UploadFeederState(),
    )

    assert raw_body.failures == [UPLOAD_SOURCE_FAILURE]
    assert events == ["fail", "iterator_close", "source_close"]


async def test_async_feeder_reports_source_cancelled_error() -> None:
    source = _FailingAsyncSource(asyncio.CancelledError())
    raw_body = RetryingAsyncRawBody(fail_results=[True])

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(),
    )

    assert raw_body.failures == ["CancelledError"]
    assert source.close_calls == 1


def test_sync_feeder_propagates_source_base_exception() -> None:
    source = _FailingSyncSource(GeneratorExit(UPLOAD_SOURCE_FAILURE))
    raw_body = _RecordingSyncRawBody()

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        feed_sync_upload_body(
            raw_body,
            source,
            upload_cleanup.UploadSourceCleanup(source),
            UploadFeederState(),
        )

    assert raw_body.failures == []
    assert raw_body.closed is True
    assert source.close_calls == 1


async def test_async_feeder_propagates_source_base_exception() -> None:
    source = _FailingAsyncSource(GeneratorExit(UPLOAD_SOURCE_FAILURE))
    raw_body = RetryingAsyncRawBody(fail_results=[True])

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        await feed_async_upload_body(
            raw_body,
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(),
        )

    assert raw_body.failures == []
    assert raw_body.is_closed() is True
    assert raw_body.events == ["close"]
    assert source.close_calls == 1


async def test_async_feeder_cancellation_during_control_cleanup_wins() -> None:
    source = _BlockingControlAsyncSource()
    task = asyncio.create_task(
        feed_async_upload_body(
            RetryingAsyncRawBody(),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(),
        ),
    )
    await source.close_started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    source.close_release.set()

    await asyncio.wait_for(source.close_finished.wait(), timeout=1.0)
    assert source.close_calls == 1


def test_sync_feeder_closes_distinct_iterator_after_exact_length() -> None:
    events: list[str] = []
    source = _SeparateSyncIteratorSource(events)
    raw_body = _RecordingSyncRawBody(events)

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        UploadFeederState(content_length=1),
    )

    assert raw_body.final_chunks == [b"x"]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["iterator_close", "source_close", "final"]


def test_sync_feeder_closes_source_when_iterator_cleanup_is_interrupted() -> None:
    events: list[str] = []
    source = _SeparateSyncIteratorSource(
        events,
        close_error=GeneratorExit(UPLOAD_SOURCE_FAILURE),
    )

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        feed_sync_upload_body(
            _RecordingSyncRawBody(events),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            UploadFeederState(),
        )

    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["send", "iterator_close", "source_close"]


def test_sync_feeder_preserves_first_cleanup_base_exception() -> None:
    events: list[str] = []
    iterator_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    source = _SeparateSyncIteratorSource(
        events,
        close_error=iterator_error,
        source_close_error=source_error,
    )

    with pytest.raises(GeneratorExit) as exc_info:
        feed_sync_upload_body(
            _RecordingSyncRawBody(events),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            UploadFeederState(),
        )

    assert exc_info.value is iterator_error
    assert source.close_calls == 1
    assert events == ["send", "iterator_close", "source_close"]


def test_sync_feeder_finishes_after_closing_distinct_iterator_at_eof() -> None:
    events: list[str] = []
    source = _SeparateSyncIteratorSource(events)
    raw_body = _RecordingSyncRawBody(events)

    feed_sync_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        UploadFeederState(),
    )

    assert raw_body.sent_chunks == [b"x"]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["send", "iterator_close", "source_close", "finish"]


async def test_async_feeder_closes_distinct_iterator_after_exact_length() -> None:
    events: list[str] = []
    source = _SeparateAsyncIteratorSource(events)
    raw_body = RetryingAsyncRawBody(send_results=[True], events=events)

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(content_length=1),
    )

    assert raw_body.final_chunks == [b"x"]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["iterator_close", "source_close", "final"]


async def test_async_feeder_reports_terminal_send_error() -> None:
    source = AsyncChunks((b"x",))
    raw_body = RetryingAsyncRawBody(fail_results=[True])
    raw_body.send_final_nowait = Mock(side_effect=ValueError(UPLOAD_SOURCE_FAILURE))

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(content_length=1),
    )

    assert raw_body.failures == [UPLOAD_SOURCE_FAILURE]


async def test_async_feeder_propagates_terminal_send_control_error() -> None:
    terminal_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source = AsyncChunks((b"x",))
    raw_body = RetryingAsyncRawBody()
    raw_body.send_final_nowait = Mock(side_effect=terminal_error)

    with pytest.raises(GeneratorExit) as exc_info:
        await feed_async_upload_body(
            raw_body,
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(content_length=1),
        )

    assert exc_info.value is terminal_error
    assert raw_body.is_closed() is True


async def test_async_feeder_closes_source_when_iterator_cleanup_is_interrupted() -> None:
    events: list[str] = []
    source = _SeparateAsyncIteratorSource(
        events,
        close_error=GeneratorExit(UPLOAD_SOURCE_FAILURE),
    )

    with pytest.raises(GeneratorExit, match=UPLOAD_SOURCE_FAILURE):
        await feed_async_upload_body(
            RetryingAsyncRawBody(send_results=[True], events=events),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(content_length=1),
        )

    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["iterator_close", "source_close", "close"]


async def test_async_feeder_preserves_first_cleanup_base_exception() -> None:
    events: list[str] = []
    iterator_error = GeneratorExit(UPLOAD_SOURCE_FAILURE)
    source_error = GeneratorExit(SECONDARY_CLEANUP_FAILURE)
    source = _SeparateAsyncIteratorSource(
        events,
        close_error=iterator_error,
        source_close_error=source_error,
    )

    with pytest.raises(GeneratorExit) as exc_info:
        await feed_async_upload_body(
            RetryingAsyncRawBody(send_results=[True], events=events),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(content_length=1),
        )

    assert exc_info.value is iterator_error
    assert source.close_calls == 1
    assert events == ["iterator_close", "source_close", "close"]


async def test_async_feeder_fails_before_closing_distinct_iterator() -> None:
    events: list[str] = []
    source = _SeparateAsyncIteratorSource(
        events,
        error=ValueError(UPLOAD_SOURCE_FAILURE),
    )
    raw_body = RetryingAsyncRawBody(fail_results=[True], events=events)

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(),
    )

    assert raw_body.failures == [UPLOAD_SOURCE_FAILURE]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1
    assert events == ["fail", "iterator_close", "source_close"]


async def test_async_feeder_preserves_reported_source_error_over_cleanup_control_error() -> None:
    events: list[str] = []
    source = _SeparateAsyncIteratorSource(
        events,
        error=ValueError(UPLOAD_SOURCE_FAILURE),
        source_close_error=GeneratorExit(SECONDARY_CLEANUP_FAILURE),
    )
    raw_body = RetryingAsyncRawBody(fail_results=[True], events=events)

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(),
    )

    assert raw_body.failures == [UPLOAD_SOURCE_FAILURE]
    assert events == ["fail", "iterator_close", "source_close"]


async def test_async_feeder_closes_iterator_before_dependent_source() -> None:
    events: list[str] = []
    source = _DependentAsyncSource(events)

    await feed_async_upload_body(
        RetryingAsyncRawBody(send_results=[True], events=events),
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(content_length=1),
    )

    assert source.closed_after_iterator is True
    assert events == [
        "iterator_close_started",
        "iterator_close_finished",
        "source_close",
        "final",
    ]


async def test_async_feeder_bounds_dependent_cleanup_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    source = _DelayedDependentAsyncSource(events)
    monkeypatch.setattr(upload_cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", 0.01)
    task = asyncio.create_task(
        feed_async_upload_body(
            RetryingAsyncRawBody(send_results=[True], events=events),
            source,
            upload_cleanup.UploadSourceCleanup(source),
            asyncio.Event(),
            UploadFeederState(content_length=1),
        ),
    )
    await source.iterator.close_started.wait()
    await asyncio.wait_for(task, timeout=1.0)

    assert source.close_started.is_set() is False
    assert events == ["iterator_close_started", "final"]

    source.iterator.close_release.set()
    await asyncio.wait_for(source.close_finished.wait(), timeout=1.0)
    assert source.closed_after_iterator is True
    assert events == [
        "iterator_close_started",
        "final",
        "iterator_close_finished",
        "source_close",
    ]


async def test_async_feeder_stops_after_closed_body_rejects_chunk() -> None:
    source = _SeparateAsyncIteratorSource([])
    raw_body = RetryingAsyncRawBody(send_results=[False], closed=True)

    await feed_async_upload_body(
        raw_body,
        source,
        upload_cleanup.UploadSourceCleanup(source),
        asyncio.Event(),
        UploadFeederState(),
    )

    assert raw_body.sent_chunks == [b"x"]
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1


async def test_async_sync_source_cancellation_closes_off_event_loop() -> None:
    source = _BlockingSyncClose()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    raw_body: Any = object()
    task = asyncio.create_task(
        feed_async_upload_body(
            raw_body,
            source,
            source_cleanup,
            asyncio.Event(),
            UploadFeederState(),
        ),
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


async def test_async_sync_source_cancellation_wins_over_late_control_error() -> None:
    source = _CancellationControlSyncSource()
    source_cleanup = upload_cleanup.UploadSourceCleanup(source)
    feeder_state = UploadFeederState()
    task = asyncio.create_task(
        feed_async_upload_body(
            RetryingAsyncRawBody(),
            source,
            source_cleanup,
            asyncio.Event(),
            feeder_state,
        ),
    )
    assert await asyncio.to_thread(source.iteration_started.wait, 1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    assert source.close_finished.wait(1.0)
    assert source.close_calls == 1
    assert feeder_state.get() is None


async def test_async_upload_ready_notification_ignores_loop_close_race() -> None:
    source = AsyncChunks((b"payload",))
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    _notify_async_body(body, _ClosingLoop())
    await body.aclose()

    assert source.close_calls == 1


async def test_async_upload_ready_notification_ignores_closed_loop() -> None:
    source = AsyncChunks((b"payload",))
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    _notify_async_body(body, _ClosedLoop())
    await body.aclose()

    assert source.close_calls == 1


async def test_async_streaming_body_bounds_feeder_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body: Any = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(AsyncChunks(())),
    )
    pending: Future[None] = Future()
    _set_async_body_feeders(body, [(pending, UploadFeederState())])
    monkeypatch.setattr(upload_runtime, "ASYNC_UPLOAD_FEEDER_JOIN_TIMEOUT", 0.01)

    assert await _drain_async_body_feeders(body) is None

    pending.cancel()
    _set_async_body_feeders(body, [])
    await body.aclose()


async def test_async_streaming_body_waits_for_actual_feeder_before_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ConcurrentCloseSensitiveAsyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    await source.iteration_started.wait()

    close_task = asyncio.create_task(body.aclose())
    await source.cancellation_started.wait()
    await asyncio.sleep(0)

    assert close_task.done() is False
    assert source.close_calls == 0
    source.iteration_release.set()
    await asyncio.wait_for(close_task, timeout=1.0)

    assert source.close_calls == 1
    assert source.concurrent_close is False
    assert source.closed is True


def test_sync_streaming_body_does_not_retry_failed_interrupt_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ConcurrentCloseSensitiveSyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_sync_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    assert source.iteration_started.wait(1.0)

    body.close()

    assert source.concurrent_close is True
    assert source.closed is False
    source.iteration_release.set()
    assert source.iteration_finished.wait(1.0)
    body.close()

    assert source.close_calls == 1
    assert source.closed is False


async def test_async_streaming_body_does_not_retry_failed_interrupt_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _ConcurrentCloseSensitiveSyncSource()
    monkeypatch.setattr(
        "foghttp._upload_body.runtime._foghttp.RawUploadBody",
        RecordingRawUploadBody,
    )
    body = upload_runtime.prepare_async_upload_body(
        upload_runtime.RequestBody.streaming_body(source),
    )
    raw_body = body.raw_body
    assert raw_body is not None
    raw_body.start_callback(raw_body)
    assert await asyncio.to_thread(source.iteration_started.wait, 1.0)

    await body.aclose()
    assert await asyncio.to_thread(source.close_attempted.wait, 1.0)

    assert source.concurrent_close is True
    assert source.closed is False
    source.iteration_release.set()
    assert await asyncio.to_thread(source.iteration_finished.wait, 1.0)
    await body.aclose()

    assert source.close_calls == 1
    assert source.closed is False


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
    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        self.finished.set()
        if self._error is not None:
            raise self._error


class _ContextRecordingAsyncClose:
    def __init__(self, request_context: ContextVar[str], observations: list[str]) -> None:
        self._request_context = request_context
        self._observations = observations

    def __aiter__(self) -> _ContextRecordingAsyncClose:
        return self

    async def __anext__(self) -> bytes:
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self._observations.append(self._request_context.get())


class _ContextClassifiedAsyncClose:
    def __init__(
        self,
        request_context: ContextVar[str],
        observations: list[tuple[str, str]],
    ) -> None:
        self._request_context = request_context
        self._observations = observations

    @property
    def __aiter__(self) -> Callable[[], object]:
        self._observations.append(("classify", self._request_context.get()))
        return lambda: self

    async def aclose(self) -> None:
        self._observations.append(("close", self._request_context.get()))


class _ContextRecordingSyncSource:
    def __init__(self, request_context: ContextVar[str], observations: list[str]) -> None:
        self._request_context = request_context
        self._observations = observations

    def __iter__(self) -> Iterator[bytes]:
        return iter(())

    def close(self) -> None:
        self._observations.append(self._request_context.get())


class _FailingCloseLookup:
    def __init__(self) -> None:
        self.lookup_calls = 0

    @property
    def close(self) -> None:
        self.lookup_calls += 1
        raise RuntimeError(SECONDARY_CLEANUP_FAILURE)


class _FailingAsyncCloseLookup:
    def __init__(self) -> None:
        self.lookup_calls = 0

    @property
    def aclose(self) -> None:
        self.lookup_calls += 1
        raise RuntimeError(SECONDARY_CLEANUP_FAILURE)


class _FailingAsyncLookupSyncSource(SyncChunks):
    @property
    def __aiter__(self) -> object:
        raise RuntimeError(UPLOAD_SOURCE_FAILURE)


class _CancelledAsyncClose:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        raise asyncio.CancelledError


class _GcBlockedAsyncClose:
    def __init__(self, started: asyncio.Event) -> None:
        self._release = asyncio.Event()
        self._started = started

    async def aclose(self) -> None:
        self._started.set()
        await self._release.wait()


class _UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError(ERROR_FORMATTING_FAILURE)


class _FailingSyncSource:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        raise self._error

    def close(self) -> None:
        self.close_calls += 1


class _FailingAsyncSource:
    def __init__(self, error: BaseException) -> None:
        self._error = error
        self.close_calls = 0

    def __aiter__(self) -> _FailingAsyncSource:
        return self

    async def __anext__(self) -> bytes:
        raise self._error

    async def aclose(self) -> None:
        self.close_calls += 1


class _RecordingSyncRawBody:
    def __init__(self, events: list[str] | None = None) -> None:
        self.closed = False
        self.failures: list[str] = []
        self.sent_chunks: list[bytes] = []
        self.final_chunks: list[bytes] = []
        self.events = [] if events is None else events

    def fail(self, message: str) -> None:
        self.failures.append(message)
        self.events.append("fail")

    def send_final(self, chunk: bytes) -> bool:
        self.final_chunks.append(chunk)
        self.events.append("final")
        return True

    def send(self, chunk: bytes) -> bool:
        self.sent_chunks.append(chunk)
        self.events.append("send")
        return True

    def finish(self) -> None:
        self.events.append("finish")

    def close(self) -> None:
        self.closed = True


class _ClosableSyncIterator:
    def __init__(
        self,
        events: list[str],
        close_error: BaseException | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.close_calls = 0
        self._sent = False
        self._events = events
        self._close_error = close_error
        self._error = error

    def __iter__(self) -> _ClosableSyncIterator:
        return self

    def __next__(self) -> bytes:
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        if self._sent:
            raise StopIteration
        self._sent = True
        return b"x"

    def close(self) -> None:
        self.close_calls += 1
        self._events.append("iterator_close")
        if self._close_error is not None:
            raise self._close_error


class _SeparateSyncIteratorSource:
    def __init__(
        self,
        events: list[str],
        close_error: BaseException | None = None,
        source_close_error: BaseException | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.iterator = _ClosableSyncIterator(events, close_error, error)
        self.close_started = threading.Event()
        self.close_calls = 0
        self._events = events
        self._source_close_error = source_close_error

    def __iter__(self) -> _ClosableSyncIterator:
        return self.iterator

    def close(self) -> None:
        self.close_calls += 1
        self._events.append("source_close")
        self.close_started.set()
        if self._source_close_error is not None:
            raise self._source_close_error


class _ClosableAsyncIterator:
    def __init__(
        self,
        events: list[str],
        error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.close_calls = 0
        self._sent = False
        self._events = events
        self._error = error
        self._close_error = close_error

    def __aiter__(self) -> _ClosableAsyncIterator:
        return self

    async def __anext__(self) -> bytes:
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"x"

    async def aclose(self) -> None:
        self.close_calls += 1
        self._events.append("iterator_close")
        if self._close_error is not None:
            raise self._close_error


class _SeparateAsyncIteratorSource:
    def __init__(
        self,
        events: list[str],
        error: BaseException | None = None,
        close_error: BaseException | None = None,
        source_close_error: BaseException | None = None,
    ) -> None:
        self.iterator = _ClosableAsyncIterator(events, error, close_error)
        self.close_calls = 0
        self._events = events
        self._source_close_error = source_close_error

    def __aiter__(self) -> _ClosableAsyncIterator:
        return self.iterator

    async def aclose(self) -> None:
        self.close_calls += 1
        self._events.append("source_close")
        if self._source_close_error is not None:
            raise self._source_close_error


class _DependentAsyncIterator:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._sent = False
        self.closed = False

    def __aiter__(self) -> _DependentAsyncIterator:
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"x"

    async def aclose(self) -> None:
        self._events.append("iterator_close_started")
        await asyncio.sleep(0)
        self.closed = True
        self._events.append("iterator_close_finished")


class _DependentAsyncSource:
    def __init__(self, events: list[str]) -> None:
        self.iterator = _DependentAsyncIterator(events)
        self._events = events
        self.closed_after_iterator = False

    def __aiter__(self) -> _DependentAsyncIterator:
        return self.iterator

    async def aclose(self) -> None:
        self.closed_after_iterator = self.iterator.closed
        self._events.append("source_close")


class _DelayedDependentAsyncIterator:
    def __init__(self, events: list[str]) -> None:
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self._events = events
        self._sent = False
        self.closed = False

    def __aiter__(self) -> _DelayedDependentAsyncIterator:
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"x"

    async def aclose(self) -> None:
        self._events.append("iterator_close_started")
        self.close_started.set()
        await self.close_release.wait()
        self.closed = True
        self._events.append("iterator_close_finished")


class _DelayedDependentAsyncSource:
    def __init__(self, events: list[str]) -> None:
        self.iterator = _DelayedDependentAsyncIterator(events)
        self.close_started = asyncio.Event()
        self.close_finished = asyncio.Event()
        self._events = events
        self.closed_after_iterator = False

    def __aiter__(self) -> _DelayedDependentAsyncIterator:
        return self.iterator

    async def aclose(self) -> None:
        self.close_started.set()
        self.closed_after_iterator = self.iterator.closed
        self._events.append("source_close")
        self.close_finished.set()


class _ConcurrentCloseSensitiveAsyncSource:
    def __init__(self) -> None:
        self.iteration_started = asyncio.Event()
        self.cancellation_started = asyncio.Event()
        self.iteration_release = asyncio.Event()
        self.close_calls = 0
        self.concurrent_close = False
        self.closed = False
        self._iteration_active = False

    def __aiter__(self) -> _ConcurrentCloseSensitiveAsyncSource:
        return self

    async def __anext__(self) -> bytes:
        self._iteration_active = True
        self.iteration_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancellation_started.set()
            await self.iteration_release.wait()
            raise
        finally:
            self._iteration_active = False

    async def aclose(self) -> None:
        self.close_calls += 1
        if self._iteration_active:
            self.concurrent_close = True
            raise RuntimeError(CONCURRENT_SOURCE_CLOSE)
        self.closed = True


class _ConcurrentCloseSensitiveSyncSource:
    def __init__(self) -> None:
        self.iteration_started = threading.Event()
        self.iteration_finished = threading.Event()
        self.iteration_release = threading.Event()
        self.close_attempted = threading.Event()
        self.close_finished = threading.Event()
        self.close_calls = 0
        self.concurrent_close = False
        self.closed = False
        self._iteration_active = False

    def __iter__(self) -> _ConcurrentCloseSensitiveSyncSource:
        return self

    def __next__(self) -> bytes:
        self._iteration_active = True
        self.iteration_started.set()
        self.iteration_release.wait()
        self._iteration_active = False
        self.iteration_finished.set()
        raise StopIteration

    def close(self) -> None:
        self.close_calls += 1
        self.close_attempted.set()
        if self._iteration_active:
            self.concurrent_close = True
            raise ValueError(CONCURRENT_SOURCE_CLOSE)
        self.closed = True
        self.close_finished.set()


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


class _BlockingControlSyncSource:
    def __init__(self) -> None:
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.close_finished = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    def close(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        self.close_release.wait()
        self.close_finished.set()


class _BlockingControlAsyncSource:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_finished = asyncio.Event()
        self.close_calls = 0

    def __aiter__(self) -> _BlockingControlAsyncSource:
        return self

    async def __anext__(self) -> bytes:
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.close_release.wait()
        self.close_finished.set()


class _CancellationControlSyncSource:
    def __init__(self) -> None:
        self.iteration_started = threading.Event()
        self.iteration_release = threading.Event()
        self.close_finished = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        self.iteration_started.set()
        self.iteration_release.wait()
        raise GeneratorExit(UPLOAD_SOURCE_FAILURE)

    def close(self) -> None:
        self.close_calls += 1
        self.iteration_release.set()
        self.close_finished.set()


class _ClosingLoop:
    def is_closed(self) -> bool:
        return False

    def call_soon_threadsafe(self, _callback: object) -> None:
        raise RuntimeError


class _ClosedLoop:
    def is_closed(self) -> bool:
        return True

    def call_soon_threadsafe(self, _callback: object) -> None:
        raise AssertionError
