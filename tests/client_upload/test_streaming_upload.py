from __future__ import annotations

import asyncio
import io
import os
import time
from typing import TYPE_CHECKING, Any

import orjson
import pytest

import foghttp
from foghttp.messages import STREAMING_BODY_CHUNK_UNSUPPORTED, SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED
from foghttp.methods import POST
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.transport_stats import wait_for_async_transport_stats


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


STREAMING_WRITE_TIMEOUT = 0.05
STALLED_PROVIDER_RETURN_LIMIT = 1.0
STALLED_PROVIDER_SLEEP = 2.0
STREAMING_TOTAL_TIMEOUT = 3.0
SYNC_CLOSE_FAILURE = "close failed"
ASYNC_CLOSE_FAILURE = "aclose failed"
EXPECTED_REPLAY_FACTORY_CALLS = 2
UPLOAD_SOURCE_FAILURE = "upload source exploded"


def test_sync_iterable_content_streams_chunked_body(sync_http_server: str) -> None:
    content = _sync_chunks((b"hello ", b"upload"))

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    payload = response.json()
    assert payload["body"] == "hello upload"
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert payload["headers"]["content-length"] == []


@pytest.mark.parametrize(
    "chunk",
    [
        bytearray(b"bytearray-upload"),
        memoryview(b"memoryview-upload"),
    ],
)
def test_sync_iterable_content_accepts_bytes_like_chunks(
    sync_http_server: str,
    chunk: bytearray | memoryview,
) -> None:
    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=iter((chunk,)),
        )

    assert response.json()["body"] == bytes(chunk).decode()


def test_sync_file_like_content_streams_with_known_length(sync_http_server: str) -> None:
    content = _ClosingBytesFile(b"file-upload")

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    payload = response.json()
    assert payload["body"] == "file-upload"
    assert payload["headers"]["content-length"] == [str(len(b"file-upload"))]
    assert payload["headers"]["transfer-encoding"] == []
    assert content.closed is True


def test_sync_non_regular_file_descriptor_streams_without_content_length(
    sync_http_server: str,
) -> None:
    content = _NonRegularFilenoFile(b"pipe-like-upload")

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    payload = response.json()
    assert payload["body"] == "pipe-like-upload"
    assert payload["headers"]["content-length"] == []
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert content.closed is True


def test_sync_empty_streaming_upload_sends_empty_body(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=_sync_chunks(()),
        )

    assert response.json()["body"] == ""


def test_sync_stream_response_accepts_streaming_upload(sync_http_server: str) -> None:
    content = _sync_chunks((b"stream ", b"response"))

    with (
        foghttp.Client() as client,
        client.stream(
            POST,
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        ) as response,
    ):
        payload = orjson.loads(b"".join(response.iter_bytes()))

    assert payload["body"] == "stream response"


def test_sync_client_rejects_async_streaming_body(sync_http_server: str) -> None:
    with (
        foghttp.Client() as client,
        pytest.raises(TypeError, match=SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED),
    ):
        client.post(sync_http_server, content=_async_chunks((b"not-sync",)))


def test_sync_client_rejects_async_streaming_body_factory(sync_http_server: str) -> None:
    content = _AsyncFactory((b"not-sync",))

    with (
        foghttp.Client() as client,
        pytest.raises(TypeError, match=SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED),
    ):
        client.post(sync_http_server, content=content)


def test_streaming_upload_rejects_method_preserving_redirect(sync_http_server: str) -> None:
    with (
        foghttp.Client(follow_redirects=True) as client,
        pytest.raises(foghttp.RequestError, match="non-replayable request body"),
    ):
        client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            content=_sync_chunks((b"non-replayable",)),
        )


def test_sync_streaming_upload_factory_replays_method_preserving_redirect(sync_http_server: str) -> None:
    content = _SyncFactory((b"replayable",))

    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            content=content,
        )

    assert response.json()["body"] == "replayable"
    assert len(response.history) == 1
    assert content.calls == EXPECTED_REPLAY_FACTORY_CALLS


def test_sync_streaming_upload_queue_full_does_not_consume_provider(sync_http_server: str) -> None:
    content = _TrackedSyncStream((b"queued",))

    with (
        foghttp.Client(limits=foghttp.Limits(max_active_requests=0, max_pending_requests=0)) as client,
        pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full"),
    ):
        client.post(sync_http_server, content=content)

    assert content.iterated is False
    assert content.closed is True


def test_sync_streaming_upload_pool_timeout_does_not_consume_provider(sync_http_server: str) -> None:
    content = _TrackedSyncStream((b"pending",))

    with (
        foghttp.Client(
            limits=foghttp.Limits(max_active_requests=0, max_pending_requests=1),
            timeouts=foghttp.Timeouts(pool=0.001),
        ) as client,
        pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"),
    ):
        client.post(sync_http_server, content=content)

    assert content.iterated is False
    assert content.closed is True


def test_streaming_upload_rejects_non_bytes_chunks(sync_http_server: str) -> None:
    content: Iterator[Any] = iter(["not-bytes"])

    with (
        foghttp.Client() as client,
        pytest.raises(foghttp.RequestError, match=STREAMING_BODY_CHUNK_UNSUPPORTED),
    ):
        client.post(sync_http_server, content=content)


def test_sync_streaming_upload_reports_source_error(sync_http_server: str) -> None:
    content = _SyncExplodingStream((b"first",))

    with (
        foghttp.Client() as client,
        pytest.raises(foghttp.RequestError, match=UPLOAD_SOURCE_FAILURE),
    ):
        client.post(sync_http_server, content=content)


def test_sync_streaming_upload_write_timeout_covers_stalled_provider(sync_http_server: str) -> None:
    def content() -> Iterator[bytes]:
        yield b"first"
        time.sleep(STALLED_PROVIDER_SLEEP)
        yield b"second"

    started = time.perf_counter()
    with (
        foghttp.Client(
            timeouts=foghttp.Timeouts(write=STREAMING_WRITE_TIMEOUT, total=STREAMING_TOTAL_TIMEOUT),
        ) as client,
        pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info,
    ):
        client.post(sync_http_server, content=content())
    elapsed = time.perf_counter() - started

    assert exc_info.value.phase == "request_body"
    assert elapsed < STALLED_PROVIDER_RETURN_LIMIT


def test_sync_streaming_upload_ignores_source_close_error(sync_http_server: str) -> None:
    content = _SyncCloseRaises((b"close ", b"raises"))

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    assert response.json()["body"] == "close raises"


async def test_async_iterable_content_streams_chunked_body(http_server: str) -> None:
    content = _async_chunks((b"async ", b"upload"))

    async with foghttp.AsyncClient() as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    payload = response.json()
    assert payload["body"] == "async upload"
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert payload["headers"]["content-length"] == []


@pytest.mark.parametrize(
    "chunk",
    [
        bytearray(b"async-bytearray-upload"),
        memoryview(b"async-memoryview-upload"),
    ],
)
async def test_async_iterable_content_accepts_bytes_like_chunks(
    http_server: str,
    chunk: bytearray | memoryview,
) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=_async_chunks((chunk,)),
        )

    assert response.json()["body"] == bytes(chunk).decode()


async def test_async_empty_streaming_upload_sends_empty_body(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=_async_chunks(()),
        )

    assert response.json()["body"] == ""


async def test_async_streaming_upload_factory_replays_method_preserving_redirect(http_server: str) -> None:
    content = _AsyncFactory((b"async-replayable",))

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
            content=content,
        )

    assert response.json()["body"] == "async-replayable"
    assert len(response.history) == 1
    assert content.calls == EXPECTED_REPLAY_FACTORY_CALLS


async def test_async_streaming_upload_queue_full_does_not_consume_provider(http_server: str) -> None:
    content = _TrackedAsyncStream((b"queued",))

    async with foghttp.AsyncClient(limits=foghttp.Limits(max_active_requests=0, max_pending_requests=0)) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire queue is full"):
            await client.post(http_server, content=content)

    assert content.iterated is False
    assert content.closed is True


async def test_async_streaming_upload_pool_timeout_does_not_consume_provider(http_server: str) -> None:
    content = _TrackedAsyncStream((b"pending",))

    async with foghttp.AsyncClient(
        limits=foghttp.Limits(max_active_requests=0, max_pending_requests=1),
        timeouts=foghttp.Timeouts(pool=0.001),
    ) as client:
        with pytest.raises(foghttp.PoolTimeout, match="request acquire timeout expired"):
            await client.post(http_server, content=content)

    assert content.iterated is False
    assert content.closed is True


async def test_async_client_accepts_sync_file_like_upload(http_server: str) -> None:
    content = _ClosingBytesFile(b"async-file-upload")

    async with foghttp.AsyncClient() as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    payload = response.json()
    assert payload["body"] == "async-file-upload"
    assert payload["headers"]["content-length"] == [str(len(b"async-file-upload"))]
    assert content.closed is True


async def test_async_streaming_upload_write_timeout_covers_stalled_provider(http_server: str) -> None:
    async def content() -> AsyncIterator[bytes]:
        yield b"first"
        await asyncio.sleep(STREAMING_WRITE_TIMEOUT * 4)
        yield b"second"

    async with foghttp.AsyncClient(timeouts=foghttp.Timeouts(write=STREAMING_WRITE_TIMEOUT, total=1.0)) as client:
        with pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info:
            await client.post(http_server, content=content())

    assert exc_info.value.phase == "request_body"


async def test_async_streaming_upload_reports_source_error(http_server: str) -> None:
    content = _AsyncExplodingStream((b"first",))

    async with foghttp.AsyncClient() as client:
        with pytest.raises(foghttp.RequestError, match=UPLOAD_SOURCE_FAILURE):
            await client.post(http_server, content=content)


async def test_async_streaming_upload_ignores_source_aclose_error(http_server: str) -> None:
    content = _AsyncCloseRaises((b"async ", b"close"))

    async with foghttp.AsyncClient() as client:
        response = await client.post(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        )

    assert response.json()["body"] == "async close"


async def test_async_stream_response_accepts_streaming_upload(http_server: str) -> None:
    content = _async_chunks((b"async ", b"stream"))

    async with (
        foghttp.AsyncClient() as client,
        client.stream(
            POST,
            f"{http_server}{SECURITY_HEADERS_PATH}",
            content=content,
        ) as response,
    ):
        payload = orjson.loads(b"".join([chunk async for chunk in response.aiter_bytes()]))

    assert payload["body"] == "async stream"


async def test_async_streaming_upload_cancellation_releases_request_slot(http_server: str) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def content() -> AsyncIterator[bytes]:
        started.set()
        yield b"first"
        await release.wait()
        yield b"second"

    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(client.post(http_server, content=content()))
        await started.wait()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 1,
            message="streaming upload did not acquire a request slot",
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        release.set()
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="streaming upload cancellation did not release request slot",
        )
        response = await client.get(http_server)

    assert response.status_code == OK


def _sync_chunks(chunks: tuple[object, ...]) -> Iterator[object]:
    yield from chunks


async def _async_chunks(chunks: tuple[object, ...]) -> AsyncIterator[object]:
    for chunk in chunks:
        await asyncio.sleep(0)
        yield chunk


class _ClosingBytesFile:
    def __init__(self, content: bytes) -> None:
        self._file = io.BytesIO(content)
        self.closed = False

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        self.closed = True
        self._file.close()


class _NonRegularFilenoFile:
    def __init__(self, content: bytes) -> None:
        self._file = io.BytesIO(content)
        self._read_fd, self._write_fd = os.pipe()
        self.closed = False

    def read(self, size: int = -1, /) -> bytes:
        return self._file.read(size)

    def fileno(self) -> int:
        return self._read_fd

    def tell(self) -> int:
        return self._file.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._file.seek(offset, whence)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._file.close()
        os.close(self._read_fd)
        os.close(self._write_fd)


class _SyncCloseRaises:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks

    def close(self) -> None:
        raise RuntimeError(SYNC_CLOSE_FAILURE)


class _AsyncCloseRaises:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk

    async def aclose(self) -> None:
        raise RuntimeError(ASYNC_CLOSE_FAILURE)


class _TrackedSyncStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.iterated = False
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        self.iterated = True
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class _TrackedAsyncStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.iterated = False
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _SyncExplodingStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks
        raise RuntimeError(UPLOAD_SOURCE_FAILURE)


class _AsyncExplodingStream:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk
        raise RuntimeError(UPLOAD_SOURCE_FAILURE)


class _SyncFactory:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.calls = 0

    def __call__(self) -> Iterator[bytes]:
        self.calls += 1
        yield from self._chunks


class _AsyncFactory:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks
        self.calls = 0

    def __call__(self) -> AsyncIterator[bytes]:
        self.calls += 1
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk
