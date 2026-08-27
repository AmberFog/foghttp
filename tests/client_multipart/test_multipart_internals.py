import asyncio
from collections.abc import Iterator
import gc
import threading
from unittest.mock import AsyncMock, Mock, PropertyMock

import pytest

from foghttp._multipart.iterators import (
    aiter_file_content,
    aiter_sync_file_content,
    iter_file_content,
)
from foghttp._multipart.length import multipart_content_length
from foghttp._multipart.models import MultipartField, MultipartFile, MultipartPayload
from foghttp._multipart.normalize import normalize_multipart_body
from foghttp._multipart.parts import multipart_payload
from foghttp._multipart.stream import (
    AsyncMultipartStream,
    MultipartStream,
    MultipartStreamFactory,
)
from foghttp._multipart.sync_runner import SyncIteratorRunner
from foghttp._upload_body.chunks import body_chunk
from foghttp._upload_body.cleanup import UploadSourceFactoryFailure
from foghttp._upload_body.file_source import UPLOAD_CHUNK_SIZE
from foghttp._upload_body.thread_bridge import run_sync_in_daemon
from foghttp.messages import (
    MULTIPART_CONTENT_TYPE_UNSUPPORTED,
    MULTIPART_FILES_UNSUPPORTED,
    STREAMING_BODY_CHUNK_UNSUPPORTED,
)
from tests.client_multipart.sources import (
    AsyncChunks,
    ClosingBytesFile,
    SyncChunks,
    ThreadTrackingSyncChunks,
)


CANCELLED_MULTIPART_ITERATION_COMPLETED = "cancelled multipart iteration completed normally"
EXPECTED_MULTIPART_WORKERS = 2


def test_body_chunk_accepts_mutable_bytes_like_values() -> None:
    assert body_chunk(bytearray(b"payload")) == b"payload"
    assert body_chunk(memoryview(b"payload")) == b"payload"


def test_body_chunk_rejects_text_chunks() -> None:
    with pytest.raises(TypeError, match=STREAMING_BODY_CHUNK_UNSUPPORTED):
        body_chunk("payload")


def test_file_content_keeps_source_owned_sync_iterator_open() -> None:
    source = _SelfSyncMultipartSource()
    file = _single_file_payload(source, async_source=False).files[0]

    assert list(iter_file_content(file)) == [b"payload"]
    assert source.close_calls == 0


async def test_file_content_keeps_source_owned_async_iterator_open() -> None:
    source = _SelfAsyncMultipartSource()
    file = _single_file_payload(source, async_source=True).files[0]

    assert [chunk async for chunk in aiter_file_content(file)] == [b"payload"]
    assert source.close_calls == 0


async def test_async_file_content_rejects_sync_source() -> None:
    file = _single_file_payload(SyncChunks((b"payload",)), async_source=True).files[0]

    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        await anext(aiter_file_content(file))


async def test_async_sync_file_content_uses_dedicated_iteration_and_cleanup_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = (b"one", b"two", b"three")
    file = _single_file_payload(SyncChunks(chunks), async_source=False).files[0]
    starts = 0
    start_thread = threading.Thread.start

    def count_start(thread: threading.Thread) -> None:
        nonlocal starts
        starts += 1
        start_thread(thread)

    monkeypatch.setattr(threading.Thread, "start", count_start)

    assert [chunk async for chunk in aiter_sync_file_content(file)] == list(chunks)
    assert starts == EXPECTED_MULTIPART_WORKERS


async def test_sync_iterator_runner_tracks_queued_request_during_active_next() -> None:
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()

    def chunks() -> Iterator[bytes]:
        first_started.set()
        first_release.wait()
        yield b"first"
        second_started.set()
        second_release.wait()
        yield b"second"

    runner = SyncIteratorRunner(iter(chunks()))
    first = asyncio.create_task(runner.next())
    assert await asyncio.to_thread(first_started.wait, 1.0)
    second = asyncio.create_task(runner.next())
    await asyncio.sleep(0)
    first_release.set()

    assert await first == b"first"
    assert await asyncio.to_thread(second_started.wait, 1.0)
    assert runner.close() is True
    second_release.set()
    assert await second == b"second"
    await asyncio.wait_for(runner.wait_closed_bounded(), timeout=1.0)


async def test_sync_iterator_runner_bounds_blocking_iterator_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator = _BlockingCloseSyncIterator()
    monkeypatch.setattr(
        "foghttp._upload_body.cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT",
        0.01,
    )
    runner = SyncIteratorRunner(iterator)

    await runner.next()
    assert await asyncio.to_thread(iterator.close_started.wait, 1.0)
    assert runner.close() is False
    try:
        await asyncio.wait_for(runner.wait_closed_bounded(), timeout=1.0)
        assert iterator.close_finished.is_set() is False
    finally:
        iterator.close_release.set()

    assert await asyncio.to_thread(iterator.close_finished.wait, 1.0)
    assert iterator.close_calls == 1


def test_file_content_propagates_distinct_iterator_cleanup_error() -> None:
    cleanup_error = GeneratorExit("iterator cleanup interrupted")
    source = _SeparateSyncMultipartSource(close_error=cleanup_error)
    file = _single_file_payload(source, async_source=False).files[0]

    with pytest.raises(GeneratorExit) as exc_info:
        list(iter_file_content(file))

    assert exc_info.value is cleanup_error
    assert source.iterator.close_calls == 1


def test_file_content_preserves_iteration_error_over_cleanup_error() -> None:
    iteration_error = ValueError("iteration failed")
    source = _SeparateSyncMultipartSource(
        error=iteration_error,
        close_error=GeneratorExit("iterator cleanup interrupted"),
    )
    file = _single_file_payload(source, async_source=False).files[0]

    with pytest.raises(ValueError, match="iteration failed") as exc_info:
        list(iter_file_content(file))

    assert exc_info.value is iteration_error
    assert source.iterator.close_calls == 1


async def test_async_file_content_propagates_distinct_iterator_cleanup_error() -> None:
    cleanup_error = GeneratorExit("iterator cleanup interrupted")
    source = _SeparateAsyncMultipartSource(close_error=cleanup_error)
    file = _single_file_payload(source, async_source=True).files[0]

    with pytest.raises(GeneratorExit) as exc_info:
        [chunk async for chunk in aiter_file_content(file)]

    assert exc_info.value is cleanup_error
    assert source.iterator.close_calls == 1


async def test_async_file_content_preserves_iteration_error_over_cleanup_error() -> None:
    iteration_error = ValueError("iteration failed")
    source = _SeparateAsyncMultipartSource(
        error=iteration_error,
        close_error=GeneratorExit("iterator cleanup interrupted"),
    )
    file = _single_file_payload(source, async_source=True).files[0]

    with pytest.raises(ValueError, match="iteration failed") as exc_info:
        [chunk async for chunk in aiter_file_content(file)]

    assert exc_info.value is iteration_error
    assert source.iterator.close_calls == 1


def test_normalize_multipart_body_rejects_empty_content_type() -> None:
    with pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        normalize_multipart_body(
            data=None,
            files={"file": b"payload"},
            headers={"content-type": " ; "},
        )


def test_multipart_payload_accepts_bytes_form_fields_without_files() -> None:
    payload = multipart_payload(
        boundary="boundary",
        data={"field": b"raw"},
        files=None,
    )

    assert payload.fields == (MultipartField(name="field", content=b"raw"),)
    assert payload.files == ()


def test_multipart_payload_rejects_unsupported_file_content() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": object()},
        )


def test_multipart_payload_rejects_empty_filename() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": ("", b"payload")},
        )


def test_multipart_payload_rejects_non_string_file_field_name() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={1: b"payload"},
        )


def test_multipart_payload_rejects_unsafe_content_type() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": ("payload.bin", b"payload", "text/plain\r\nx: y")},
        )


def test_multipart_stream_closes_all_owned_sync_sources_after_base_exception() -> None:
    interrupted_source = Mock()
    interrupted_source.close.side_effect = GeneratorExit("cleanup interrupted")
    source = SyncChunks((b"payload",))
    stream = MultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="interrupted",
                    filename="interrupted.bin",
                    content=interrupted_source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
            ),
        ),
    )

    with pytest.raises(GeneratorExit, match="cleanup interrupted"):
        stream.close()

    interrupted_source.close.assert_called_once_with()
    assert source.closed is True


def test_multipart_stream_emits_exact_wire_bytes_for_field_and_file() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(MultipartField(name="description", content=b"avatar"),),
        files=(
            MultipartFile(
                name="file",
                filename="avatar.txt",
                content=b"payload",
                content_type="text/plain",
                content_length=len(b"payload"),
                replayable=True,
                async_source=False,
            ),
        ),
    )

    assert b"".join(MultipartStream(payload)) == (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="description"\r\n'
        b"\r\n"
        b"avatar\r\n"
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="avatar.txt"\r\n'
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"payload\r\n"
        b"--boundary--\r\n"
    )


def test_multipart_stream_escapes_quoted_header_parameters() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name='field"name',
                filename='path\\file"name.txt',
                content=b"",
                content_type="application/octet-stream",
                content_length=0,
                replayable=True,
                async_source=False,
            ),
        ),
    )

    assert b"".join(MultipartStream(payload)) == (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="field\\"name"; '
        b'filename="path\\\\file\\"name.txt"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        b"\r\n"
        b"--boundary--\r\n"
    )


async def test_async_multipart_stream_iterates_sync_and_async_sources() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(MultipartField(name="field", content=b"value"),),
        files=(
            MultipartFile(
                name="sync",
                filename="sync.bin",
                content=SyncChunks((b"sync",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
            MultipartFile(
                name="async",
                filename="async.bin",
                content=AsyncChunks((b"async",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=True,
            ),
        ),
    )

    body = b"".join([chunk async for chunk in AsyncMultipartStream(payload)])

    assert b"value" in body
    assert b"sync" in body
    assert b"async" in body


async def test_async_multipart_stream_reads_sync_parts_off_event_loop() -> None:
    sync_source = ThreadTrackingSyncChunks((b"sync",))
    loop_thread_id = threading.get_ident()
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="sync",
                filename="sync.bin",
                content=sync_source,
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
            MultipartFile(
                name="async",
                filename="async.bin",
                content=AsyncChunks((b"async",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=True,
            ),
        ),
    )

    body = b"".join([chunk async for chunk in AsyncMultipartStream(payload)])

    assert b"sync" in body
    assert sync_source.thread_ids
    assert loop_thread_id not in sync_source.thread_ids


async def test_async_multipart_stream_closes_sync_parts_off_event_loop() -> None:
    sync_source = ThreadTrackingSyncChunks((b"sync",))
    loop_thread_id = threading.get_ident()
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="sync",
                    filename="sync.bin",
                    content=sync_source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
            ),
        ),
    )

    await stream.aclose()

    assert sync_source.close_thread_ids
    assert loop_thread_id not in sync_source.close_thread_ids


async def test_async_multipart_stream_closes_owned_async_source() -> None:
    source = AsyncChunks((b"payload",))
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=True,
                    close_source=True,
                ),
            ),
        ),
    )

    await stream.aclose()
    assert source.closed is True


async def test_async_multipart_stream_bounds_owned_source_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _BlockingAsyncMultipartClose()
    monkeypatch.setattr(
        "foghttp._upload_body.cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT",
        0.01,
    )
    stream = AsyncMultipartStream(
        _single_file_payload(source, async_source=True),
    )

    try:
        await asyncio.wait_for(stream.aclose(), timeout=1.0)
        assert source.close_started.is_set()
        assert source.close_finished.is_set() is False
    finally:
        source.close_release.set()

    await asyncio.wait_for(source.close_finished.wait(), timeout=1.0)
    assert source.close_calls == 1


async def test_async_multipart_stream_closes_all_sources_after_base_exception() -> None:
    interrupted_source = Mock()
    interrupted_source.aclose = AsyncMock(side_effect=GeneratorExit("cleanup interrupted"))
    source = AsyncChunks((b"payload",))
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="interrupted",
                    filename="interrupted.bin",
                    content=interrupted_source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=True,
                    close_source=True,
                ),
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=True,
                    close_source=True,
                ),
            ),
        ),
    )

    with pytest.raises(GeneratorExit, match="cleanup interrupted"):
        await stream.aclose()

    interrupted_source.aclose.assert_awaited_once_with()
    assert source.closed is True


async def test_async_multipart_stream_closes_owned_sync_source() -> None:
    source = SyncChunks((b"payload",))
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
            ),
        ),
    )

    await stream.aclose()
    assert source.closed is True


def test_multipart_stream_closes_distinct_file_iterator_on_early_stop() -> None:
    source = _SeparateSyncMultipartSource()
    stream = MultipartStream(_single_file_payload(source, async_source=False))
    iterator = iter(stream)

    next(iterator)
    next(iterator)
    iterator.close()
    stream.close()

    assert source.iterator.close_calls == 1
    assert source.close_calls == 1


def test_multipart_stream_preserves_iterator_source_cleanup_order_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _OrderingSyncMultipartSource()
    monkeypatch.setattr(
        "foghttp._upload_body.cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT",
        0.01,
    )
    stream = MultipartStream(_single_file_payload(source, async_source=False))
    iterator = iter(stream)
    next(iterator)
    next(iterator)
    iterator.close()

    try:
        stream.close()
        assert source.iterator.close_started.wait(1.0)
        assert source.close_started.is_set() is False
    finally:
        source.iterator.close_release.set()

    assert source.close_started.wait(1.0)
    assert source.closed_after_iterator is True


async def test_async_multipart_stream_closes_distinct_file_iterator_on_early_stop() -> None:
    source = _SeparateAsyncMultipartSource()
    stream = AsyncMultipartStream(_single_file_payload(source, async_source=True))
    iterator = stream.__aiter__()

    await anext(iterator)
    await anext(iterator)
    await iterator.aclose()
    await stream.aclose()

    assert source.iterator.close_calls == 1
    assert source.close_calls == 1


async def test_async_multipart_stream_preserves_iterator_source_cleanup_order_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _OrderingAsyncMultipartSource()
    monkeypatch.setattr(
        "foghttp._upload_body.cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT",
        0.01,
    )
    stream = AsyncMultipartStream(_single_file_payload(source, async_source=True))
    iterator = stream.__aiter__()
    await anext(iterator)
    await anext(iterator)
    await iterator.aclose()

    try:
        await stream.aclose()
        assert source.iterator.close_started.is_set()
        assert source.close_started.is_set() is False
    finally:
        source.iterator.close_release.set()

    await asyncio.wait_for(source.close_started.wait(), timeout=1.0)
    assert source.closed_after_iterator is True


async def test_async_multipart_defers_sync_iterator_close_until_pending_next_finishes() -> None:
    source = _BlockingSeparateSyncMultipartSource()
    stream = AsyncMultipartStream(_single_file_payload(source, async_source=False))
    iterator = stream.__aiter__()
    await anext(iterator)
    chunk_task = asyncio.create_task(anext(iterator))
    assert await asyncio.to_thread(source.iterator.started.wait, 1.0)

    chunk_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await chunk_task
    await stream.aclose()

    assert await asyncio.to_thread(source.iterator.closed.wait, 1.0)
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1


async def test_async_multipart_consumes_late_pending_sync_iterator_error() -> None:
    source = _BlockingSeparateSyncMultipartSource(error=RuntimeError("late next failure"))
    stream = AsyncMultipartStream(_single_file_payload(source, async_source=False))
    iterator = stream.__aiter__()
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
        await anext(iterator)
        chunk_task = asyncio.create_task(anext(iterator))
        assert await asyncio.to_thread(source.iterator.started.wait, 1.0)

        chunk_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await chunk_task
        await stream.aclose()

        assert await asyncio.to_thread(source.iterator.closed.wait, 1.0)
        await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
    finally:
        source.iterator.release.set()
        loop.set_exception_handler(previous_exception_handler)

    assert loop_errors == []
    assert source.iterator.close_calls == 1
    assert source.close_calls == 1


def test_caller_owned_blocking_multipart_iterator_does_not_hold_loop_shutdown() -> None:
    source = _BlockingSeparateSyncMultipartSource()
    finished = threading.Event()
    errors: list[BaseException] = []

    async def consume() -> None:
        stream = AsyncMultipartStream(
            _single_file_payload(
                source,
                async_source=False,
                close_source=False,
            ),
        )
        iterator = stream.__aiter__()
        await anext(iterator)
        chunk_task = asyncio.create_task(anext(iterator))
        assert await run_sync_in_daemon(lambda: source.iterator.started.wait(1.0))
        chunk_task.cancel()
        try:
            await chunk_task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError(CANCELLED_MULTIPART_ITERATION_COMPLETED)
        await stream.aclose()

    def run() -> None:
        try:
            asyncio.run(consume())
        except BaseException as error:  # noqa: BLE001
            errors.append(error)
        finally:
            finished.set()

    owner = threading.Thread(target=run, daemon=True)
    owner.start()
    assert source.iterator.started.wait(1.0)
    try:
        assert finished.wait(1.0)
    finally:
        source.iterator.release.set()
        owner.join(1.0)

    assert errors == []
    assert owner.is_alive() is False
    assert source.iterator.closed.wait(1.0)
    assert source.iterator.close_calls == 1
    assert source.close_calls == 0


def test_multipart_stream_factory_creates_fresh_sync_stream() -> None:
    payload = _factory_payload(lambda: SyncChunks((b"sync",)))

    stream = MultipartStreamFactory(payload)()

    assert isinstance(stream, MultipartStream)
    assert b"sync" in b"".join(stream)


def test_multipart_stream_factory_chunks_file_like_product() -> None:
    source = ClosingBytesFile(b"x" * (UPLOAD_CHUNK_SIZE + 1))
    payload = _factory_payload(lambda: source)

    stream = MultipartStreamFactory(payload)()

    assert isinstance(stream, MultipartStream)
    assert b"x" * (UPLOAD_CHUNK_SIZE + 1) in b"".join(stream)
    stream.close()
    assert source.read_sizes == [UPLOAD_CHUNK_SIZE] * 3
    assert source.close_calls == 1


def test_multipart_stream_factory_closes_product_after_classification_failure() -> None:
    source_error = GeneratorExit("classification interrupted")
    source = Mock()
    type(source).read = PropertyMock(side_effect=source_error)
    payload = _factory_payload(lambda: source)

    result = MultipartStreamFactory(payload)()

    assert isinstance(result, UploadSourceFactoryFailure)
    assert result.error is source_error
    source.close.assert_called_once_with()


@pytest.mark.parametrize(
    "source_error",
    [asyncio.CancelledError(), GeneratorExit("factory interrupted")],
    ids=["cancelled", "generator-exit"],
)
def test_multipart_stream_factory_preserves_partial_sources_on_base_exception(
    source_error: BaseException,
) -> None:
    source = SyncChunks((b"opened",))

    def failing_factory() -> object:
        raise source_error

    first = _factory_payload(lambda: source)
    second = _factory_payload(failing_factory)
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=first.files + second.files,
    )

    result = MultipartStreamFactory(payload)()

    assert isinstance(result, UploadSourceFactoryFailure)
    assert result.error is source_error
    assert isinstance(result.source, MultipartStream)
    result.source.close()
    assert source.close_calls == 1


async def test_multipart_stream_factory_preserves_partial_async_source_on_base_exception() -> None:
    source = AsyncChunks((b"opened",))
    source_error = GeneratorExit("factory interrupted")

    def failing_factory() -> object:
        raise source_error

    first = _factory_payload(lambda: source)
    second = _factory_payload(failing_factory)
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=first.files + second.files,
    )

    result = MultipartStreamFactory(payload)()

    assert isinstance(result, UploadSourceFactoryFailure)
    assert result.error is source_error
    assert isinstance(result.source, AsyncMultipartStream)
    await result.source.aclose()
    assert source.close_calls == 1


async def test_multipart_stream_factory_creates_fresh_async_stream() -> None:
    payload = _factory_payload(lambda: AsyncChunks((b"async",)))

    stream = MultipartStreamFactory(payload)()

    assert isinstance(stream, AsyncMultipartStream)
    assert b"async" in b"".join([chunk async for chunk in stream])


def test_multipart_content_length_is_unknown_for_stream_part() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="file",
                filename="payload.bin",
                content=SyncChunks((b"payload",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
        ),
    )

    assert multipart_content_length(payload) is None


def _single_file_payload(
    source: object,
    *,
    async_source: bool,
    close_source: bool = True,
) -> MultipartPayload:
    return MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="file",
                filename="payload.bin",
                content=source,
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=async_source,
                close_source=close_source,
            ),
        ),
    )


class _ClosableSyncMultipartIterator:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self._sent = False
        self._error = error
        self._close_error = close_error
        self.close_calls = 0

    def __iter__(self) -> "_ClosableSyncMultipartIterator":
        return self

    def __next__(self) -> bytes:
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        if self._sent:
            raise StopIteration
        self._sent = True
        return b"payload"

    def close(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _SeparateSyncMultipartSource:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.iterator = _ClosableSyncMultipartIterator(
            error=error,
            close_error=close_error,
        )
        self.close_calls = 0

    def __iter__(self) -> _ClosableSyncMultipartIterator:
        return self.iterator

    def close(self) -> None:
        self.close_calls += 1


class _BlockingSyncMultipartIterator:
    def __init__(self, error: BaseException | None = None) -> None:
        self._error = error
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> "_BlockingSyncMultipartIterator":
        return self

    def __next__(self) -> bytes:
        self.started.set()
        self.release.wait()
        if self._error is not None:
            raise self._error
        return b"payload"

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class _BlockingCloseSyncIterator:
    def __init__(self) -> None:
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.close_finished = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> "_BlockingCloseSyncIterator":
        return self

    def __next__(self) -> bytes:
        raise StopIteration

    def close(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        self.close_release.wait()
        self.close_finished.set()


class _OrderingSyncMultipartIterator:
    def __init__(self) -> None:
        self._sent = False
        self.close_started = threading.Event()
        self.close_release = threading.Event()
        self.close_finished = threading.Event()

    def __iter__(self) -> "_OrderingSyncMultipartIterator":
        return self

    def __next__(self) -> bytes:
        if self._sent:
            raise StopIteration
        self._sent = True
        return b"payload"

    def close(self) -> None:
        self.close_started.set()
        self.close_release.wait()
        self.close_finished.set()


class _OrderingSyncMultipartSource:
    def __init__(self) -> None:
        self.iterator = _OrderingSyncMultipartIterator()
        self.close_started = threading.Event()
        self.closed_after_iterator = False

    def __iter__(self) -> _OrderingSyncMultipartIterator:
        return self.iterator

    def close(self) -> None:
        self.closed_after_iterator = self.iterator.close_finished.is_set()
        self.close_started.set()


class _BlockingSeparateSyncMultipartSource:
    def __init__(self, error: BaseException | None = None) -> None:
        self.iterator = _BlockingSyncMultipartIterator(error)
        self.close_calls = 0

    def __iter__(self) -> _BlockingSyncMultipartIterator:
        return self.iterator

    def close(self) -> None:
        self.close_calls += 1
        self.iterator.release.set()


class _ClosableAsyncMultipartIterator:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self._sent = False
        self._error = error
        self._close_error = close_error
        self.close_calls = 0

    def __aiter__(self) -> "_ClosableAsyncMultipartIterator":
        return self

    async def __anext__(self) -> bytes:
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"payload"

    async def aclose(self) -> None:
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _SeparateAsyncMultipartSource:
    def __init__(
        self,
        *,
        error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.iterator = _ClosableAsyncMultipartIterator(
            error=error,
            close_error=close_error,
        )
        self.close_calls = 0

    def __aiter__(self) -> _ClosableAsyncMultipartIterator:
        return self.iterator

    async def aclose(self) -> None:
        self.close_calls += 1


class _BlockingAsyncMultipartClose:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_finished = asyncio.Event()
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.close_release.wait()
        self.close_finished.set()


class _OrderingAsyncMultipartIterator:
    def __init__(self) -> None:
        self._sent = False
        self.close_started = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_finished = asyncio.Event()

    def __aiter__(self) -> "_OrderingAsyncMultipartIterator":
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"payload"

    async def aclose(self) -> None:
        self.close_started.set()
        await self.close_release.wait()
        self.close_finished.set()


class _OrderingAsyncMultipartSource:
    def __init__(self) -> None:
        self.iterator = _OrderingAsyncMultipartIterator()
        self.close_started = asyncio.Event()
        self.closed_after_iterator = False

    def __aiter__(self) -> _OrderingAsyncMultipartIterator:
        return self.iterator

    async def aclose(self) -> None:
        self.closed_after_iterator = self.iterator.close_finished.is_set()
        self.close_started.set()


class _SelfSyncMultipartSource:
    def __init__(self) -> None:
        self._sent = False
        self.close_calls = 0

    def __iter__(self) -> "_SelfSyncMultipartSource":
        return self

    def __next__(self) -> bytes:
        if self._sent:
            raise StopIteration
        self._sent = True
        return b"payload"

    def close(self) -> None:
        self.close_calls += 1


class _SelfAsyncMultipartSource:
    def __init__(self) -> None:
        self._sent = False
        self.close_calls = 0

    def __aiter__(self) -> "_SelfAsyncMultipartSource":
        return self

    async def __anext__(self) -> bytes:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"payload"

    async def aclose(self) -> None:
        self.close_calls += 1


def _factory_payload(factory: object) -> MultipartPayload:
    return MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="file",
                filename="payload.bin",
                content=factory,
                content_type="application/octet-stream",
                content_length=None,
                replayable=True,
                async_source=False,
                source_factory=True,
            ),
        ),
    )
