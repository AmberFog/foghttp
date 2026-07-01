import asyncio

import pytest

import foghttp
from foghttp.methods import POST
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.client_multipart.assertions import (
    assert_multipart_parts,
    multipart_parts_from_payload,
    parse_multipart_parts,
)
from tests.client_multipart.models import MultipartPart
from tests.client_multipart.sources import AsyncChunks, BlockingSyncChunks, ClosingBytesFile
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.transport_stats import wait_for_async_transport_stats


async def test_async_client_sends_multipart_files_and_form_fields(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
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

    async with foghttp.AsyncClient() as client:
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

    async with foghttp.AsyncClient() as client:
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


async def test_async_stream_multipart_rejects_method_preserving_redirect(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        with pytest.raises(foghttp.RequestError, match="non-replayable request body"):
            await client.post(
                f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
                files={"file": ("stream.bin", AsyncChunks((b"not replayable",)))},
            )


async def test_async_buffered_multipart_replays_method_preserving_redirect(http_server: str) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
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


async def test_async_stream_response_accepts_multipart_upload(http_server: str) -> None:
    async with (
        foghttp.AsyncClient() as client,
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

    async with foghttp.AsyncClient() as client:
        task = asyncio.create_task(
            client.post(
                f"{http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", source_factory)},
            ),
        )

        await asyncio.wait_for(source_created.wait(), timeout=2.0)
        source = sources[0]
        assert await asyncio.to_thread(source.started.wait, 2.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert source.closed is True
        assert await asyncio.to_thread(source.finished.wait, 2.0)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart upload cancellation did not release request slot",
        )
