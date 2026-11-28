import asyncio
from collections.abc import AsyncIterator
import time
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

import foghttp
from foghttp.messages import MULTIPART_FILES_UNSUPPORTED
from foghttp.methods import POST
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.client_multipart.assertions import (
    assert_multipart_parts,
    multipart_parts_from_payload,
    parse_multipart_parts,
)
from tests.client_multipart.models import MultipartPart
from tests.client_multipart.sources import (
    AsyncChunks,
    BlockingAsyncChunks,
    BlockingSyncChunks,
    CallableAsyncChunks,
    ClosingBytesFile,
    SyncChunks,
    TrackedFactory,
)
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.transport_stats import wait_for_async_transport_stats


EXPECTED_REPLAY_FACTORY_CALLS = 2
MULTIPART_FACTORY_FAILURE = "multipart factory failed"
CANCELLATION_TIMEOUT = 2.0
MULTIPART_TOTAL_TIMEOUT = 3.0
MULTIPART_WRITE_TIMEOUT = 0.05
STALLED_PROVIDER_RETURN_LIMIT = 1.0
STALLED_PROVIDER_SLEEP = 2.0
FAST_MULTIPART_TIMEOUTS = foghttp.Timeouts(connect=1.0, read=1.0, write=1.0, pool=0.5, total=3.0)


async def test_async_client_sends_multipart_files_and_form_fields(http_server: str) -> None:
    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            data={"description": "avatar"},
            files={"file": ("avatar.txt", b"payload", "text/plain")},
        )

    assert_multipart_parts(
        multipart_parts_from_payload(response.json()),
        [
            MultipartPart(name="description", content=b"avatar"),
            MultipartPart(
                name="file",
                filename="avatar.txt",
                content=b"payload",
                content_type="text/plain",
            ),
        ],
    )


async def test_async_client_streams_async_multipart_part(http_server: str) -> None:
    stream = AsyncChunks((b"async-", b"part"))

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            files={"stream": ("stream.bin", stream)},
        )

    payload = response.json()
    assert payload["headers"]["content-length"] == []
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert stream.closed is False
    assert_multipart_parts(
        multipart_parts_from_payload(payload),
        [
            MultipartPart(
                name="stream",
                filename="stream.bin",
                content=b"async-part",
                content_type="application/octet-stream",
            ),
        ],
    )


async def test_async_client_streams_sync_file_multipart_without_closing_external_file(http_server: str) -> None:
    file_obj = ClosingBytesFile(b"file payload", name="reports/report.txt")

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            files={"report": file_obj},
        )

    assert file_obj.closed is False
    assert_multipart_parts(
        multipart_parts_from_payload(response.json()),
        [
            MultipartPart(
                name="report",
                filename="report.txt",
                content=b"file payload",
                content_type="application/octet-stream",
            ),
        ],
    )


async def test_callable_async_provider_uses_direct_multipart_ownership(http_server: str) -> None:
    source = CallableAsyncChunks((b"direct-provider",))

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            files={"file": ("callable.bin", source)},
        )

    assert b"direct-provider" in response.content
    assert source.calls == 0
    assert source.close_calls == 0
    await source.aclose()


async def test_async_stream_multipart_rejects_method_preserving_redirect(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True, timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError, match="non-replayable request body"):
            await client.post(
                f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
                files={"file": ("stream.bin", AsyncChunks((b"not replayable",)))},
            )


async def test_async_buffered_multipart_replays_method_preserving_redirect(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True, timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
            files={"file": ("payload.txt", b"replayable")},
        )

    assert response.status_code == OK
    assert len(response.history) == 1
    assert_multipart_parts(
        parse_multipart_parts(
            content_type=response.request.headers["content-type"],
            body=response.json()["body"].encode(),
        ),
        [
            MultipartPart(
                name="file",
                filename="payload.txt",
                content=b"replayable",
                content_type="application/octet-stream",
            ),
        ],
    )


async def test_async_factory_multipart_replays_method_preserving_redirect(http_server: str) -> None:
    sources: list[AsyncChunks] = []

    def content() -> AsyncChunks:
        source = AsyncChunks((b"factory",))
        sources.append(source)
        return source

    factory = TrackedFactory(content)
    async with foghttp.AsyncClient(follow_redirects=True, timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        response = await client.post(
            f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
            files={"file": ("factory.txt", factory)},
        )

    assert response.status_code == OK
    assert len(response.history) == 1
    assert len(sources) == EXPECTED_REPLAY_FACTORY_CALLS
    assert factory.close_calls == 0
    assert all(source.close_calls == 1 for source in sources)
    assert_multipart_parts(
        parse_multipart_parts(
            content_type=response.request.headers["content-type"],
            body=response.json()["body"].encode(),
        ),
        [
            MultipartPart(
                name="file",
                filename="factory.txt",
                content=b"factory",
                content_type="application/octet-stream",
            ),
        ],
    )


async def test_async_stream_response_accepts_multipart_upload(http_server: str) -> None:
    async with (
        foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client,
        client.stream(
            POST,
            f"{http_server}{SECURITY_HEADERS_PATH}",
            files={"file": ("payload.txt", b"stream-response")},
        ) as response,
    ):
        body = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert b"stream-response" in body


async def test_async_multipart_cancellation_closes_sync_source(http_server: str) -> None:
    loop = asyncio.get_running_loop()
    source_created = asyncio.Event()
    sources: list[BlockingSyncChunks] = []

    def source_factory() -> BlockingSyncChunks:
        source = BlockingSyncChunks((b"first", b"second"))
        sources.append(source)
        loop.call_soon_threadsafe(source_created.set)
        return source

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        task = asyncio.create_task(
            client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", source_factory)},
            ),
        )

        await asyncio.wait_for(source_created.wait(), timeout=2.0)
        source = sources[0]
        try:
            assert await asyncio.to_thread(source.started.wait, 2.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=CANCELLATION_TIMEOUT)

            assert await asyncio.to_thread(source.close_finished.wait, CANCELLATION_TIMEOUT)
            assert source.close_calls == 1
            assert await asyncio.to_thread(source.finished.wait, 2.0)
            await wait_for_async_transport_stats(
                client,
                lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
                message="multipart upload cancellation did not release request slot",
            )
        finally:
            source.release.set()


async def test_async_multipart_cancellation_keeps_direct_async_source_open(http_server: str) -> None:
    source = BlockingAsyncChunks((b"first", b"second"))

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        task = asyncio.create_task(
            client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", source)},
            ),
        )

        await asyncio.wait_for(source.started.wait(), timeout=2.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=CANCELLATION_TIMEOUT)

        assert source.close_calls == 0
        await asyncio.wait_for(source.finished.wait(), timeout=2.0)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart upload cancellation did not release request slot",
        )


async def test_async_multipart_cancellation_closes_factory_async_source(http_server: str) -> None:
    source_created = asyncio.Event()
    sources: list[BlockingAsyncChunks] = []

    def source_factory() -> BlockingAsyncChunks:
        source = BlockingAsyncChunks((b"first", b"second"))
        sources.append(source)
        source_created.set()
        return source

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        task = asyncio.create_task(
            client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", source_factory)},
            ),
        )

        await asyncio.wait_for(source_created.wait(), timeout=2.0)
        source = sources[0]
        await asyncio.wait_for(source.started.wait(), timeout=2.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=CANCELLATION_TIMEOUT)

        assert source.close_calls == 1
        await asyncio.wait_for(source.finished.wait(), timeout=2.0)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart upload cancellation did not release request slot",
        )


async def test_async_streaming_multipart_write_timeout_covers_stalled_provider(http_server: str) -> None:
    async def content() -> AsyncIterator[bytes]:
        yield b"first"
        await asyncio.sleep(STALLED_PROVIDER_SLEEP)
        yield b"second"

    started = time.perf_counter()
    async with foghttp.AsyncClient(
        timeouts=foghttp.Timeouts(
            write=MULTIPART_WRITE_TIMEOUT,
            total=MULTIPART_TOTAL_TIMEOUT,
        ),
    ) as client:
        with pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info:
            await client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", content())},
            )
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart write timeout did not release request slot",
        )
    elapsed = time.perf_counter() - started

    assert exc_info.value.phase == "request_body"
    assert elapsed < STALLED_PROVIDER_RETURN_LIMIT


async def test_async_multipart_coroutine_factory_fails_cleanly(http_server: str) -> None:
    async def invalid_part() -> AsyncChunks:
        return AsyncChunks((b"invalid",))

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
            await client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files=cast("Any", {"file": ("invalid.bin", invalid_part)}),
            )
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart factory failure did not release request slot",
        )


@pytest.mark.parametrize(
    ("has_sync_close", "with_sync_part"),
    [(False, False), (True, False), (True, True)],
    ids=["aclose-only", "close-and-aclose", "after-sync-part"],
)
async def test_async_multipart_classification_failure_closes_factory_source_on_caller_loop(
    http_server: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    has_sync_close: bool,
    with_sync_part: bool,
) -> None:
    caller_loop = asyncio.get_running_loop()
    release: asyncio.Future[None] = caller_loop.create_future()
    close_loops: list[asyncio.AbstractEventLoop] = []
    failure = ValueError("multipart classification failed")

    class Source(AsyncChunks):
        @property
        def read(self) -> object:
            raise failure

        async def aclose(self) -> None:
            close_loops.append(asyncio.get_running_loop())
            caller_loop.call_soon_threadsafe(release.set_result, None)
            await release
            await super().aclose()

    source = Source(())
    sync_close = Mock()
    if has_sync_close:
        monkeypatch.setattr(source, "close", sync_close, raising=False)
    factory = TrackedFactory(lambda: source)
    files = {}
    prefix = SyncChunks(())
    prefix_aclose = AsyncMock()
    if with_sync_part:
        monkeypatch.setattr(prefix, "aclose", prefix_aclose, raising=False)
        files["first"] = ("first.bin", TrackedFactory(lambda: prefix))
    files["file"] = ("broken.bin", factory)
    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        with pytest.raises(ValueError, match=str(failure)) as caught:
            await client.post(f"{http_server}{SECURITY_HEADERS_PATH}", files=files)
        assert source.closed

    assert caught.value is failure
    assert factory.calls == 1
    assert close_loops == [caller_loop]
    assert source.close_calls == 1
    sync_close.assert_not_called()
    if with_sync_part:
        assert prefix.close_calls == 1
        prefix_aclose.assert_not_called()


@pytest.mark.parametrize("failure_type", [RuntimeError, GeneratorExit, StopIteration])
@pytest.mark.parametrize("streaming", [False, True], ids=["buffered-response", "streaming-response"])
async def test_async_multipart_closes_sources_when_later_factory_fails(
    http_server: str,
    failure_type: type[BaseException],
    *,
    streaming: bool,
) -> None:
    source = AsyncChunks((b"opened",))
    first_factory = TrackedFactory(lambda: source)
    failure = failure_type(MULTIPART_FACTORY_FAILURE)
    original_context = LookupError("factory context")

    def failing_part() -> object:
        try:
            raise original_context
        except LookupError as error:
            raise failure from error

    second_factory = TrackedFactory(failing_part)
    last_factory = TrackedFactory(lambda: AsyncChunks(()))
    files = [
        ("first", ("first.bin", first_factory)),
        ("second", ("second.bin", second_factory)),
        ("last", ("last.bin", last_factory)),
    ]
    url = f"{http_server}{SECURITY_HEADERS_PATH}"
    expected = RuntimeError if isinstance(failure, StopIteration) else failure_type
    message = "StopIteration" if isinstance(failure, StopIteration) else MULTIPART_FACTORY_FAILURE

    async def send(client: foghttp.AsyncClient) -> None:
        if streaming:
            async with client.stream(POST, url, files=files):
                pytest.fail("multipart factory failure yielded a response")
        else:
            await client.post(url, files=files)

    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client:
        async with asyncio.timeout(CANCELLATION_TIMEOUT):
            with pytest.raises(expected, match=message) as caught:
                await send(client)
        if isinstance(failure, StopIteration):
            assert caught.value.__cause__ is failure
        else:
            assert caught.value is failure
        assert failure.__context__ is original_context
        assert failure.__cause__ is original_context
        assert source.close_calls == 1
    assert first_factory.calls == second_factory.calls == 1
    assert last_factory.calls == 0
    assert first_factory.close_calls == second_factory.close_calls == last_factory.close_calls == 0


async def test_async_multipart_can_cancel_cleanup_after_factory_generator_exit(
    http_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AsyncChunks((b"opened",))
    closing = asyncio.Event()
    release = asyncio.Event()
    closed = asyncio.Event()
    original_close = source.aclose

    async def gated_close() -> None:
        closing.set()
        await release.wait()
        await original_close()
        closed.set()

    def failing_part() -> object:
        raise GeneratorExit(MULTIPART_FACTORY_FAILURE)

    monkeypatch.setattr(source, "aclose", gated_close)
    files = [("first", ("first.bin", lambda: source)), ("second", ("second.bin", failing_part))]
    async with foghttp.AsyncClient(timeouts=FAST_MULTIPART_TIMEOUTS) as client, asyncio.timeout(CANCELLATION_TIMEOUT):
        request = asyncio.create_task(client.post(f"{http_server}{SECURITY_HEADERS_PATH}", files=files))
        try:
            await closing.wait()
            request.cancel("cancel during cleanup")
            with pytest.raises(asyncio.CancelledError, match="cancel during cleanup"):
                await request
        finally:
            release.set()
        await closed.wait()
        assert source.close_calls == 1
