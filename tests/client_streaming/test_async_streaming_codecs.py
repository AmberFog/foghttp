from collections.abc import AsyncIterator, Callable

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming.constants import (
    BOM_TEXT_STREAM_CHUNKS,
    TEXT_LINES,
    TEXT_LINES_BODY,
    TEXT_LINES_STREAM_PATH,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_streaming.text_codec_cases import NON_TEXT_CODECS, NON_TEXT_CONTENT_TYPES
from tests.support.transport_stats import wait_for_async_transport_stats


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
async def test_non_text_charset_falls_back_without_sniffing_stream_bom(
    codec_streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert response.encoding == "utf-8"
        assert client.stats().active_requests == 1
        chunks = [chunk async for chunk in response.aiter_text()]

        assert all(isinstance(chunk, str) for chunk in chunks)
        assert "".join(chunks) == "\ufeff" + TEXT_LINES_BODY


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
async def test_non_text_charset_lines_are_text(
    codec_streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        lines = [line async for line in response.aiter_lines()]

        assert all(isinstance(line, str) for line in lines)
        assert lines == ["\ufeff" + TEXT_LINES[0], *TEXT_LINES[1:]]


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
async def test_non_text_charset_preserves_raw_bytes(
    codec_streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == b"".join(BOM_TEXT_STREAM_CHUNKS)


@pytest.mark.parametrize("encoding", NON_TEXT_CODECS)
@pytest.mark.parametrize(
    "text_iterator",
    [
        pytest.param(foghttp.AsyncStreamResponse.aiter_text, id="text"),
        pytest.param(foghttp.AsyncStreamResponse.aiter_lines, id="lines"),
    ],
)
async def test_non_text_override_fails_lazily_and_aborts_once(
    streaming_server: AsyncStreamingServer,
    encoding: str,
    text_iterator: Callable[..., AsyncIterator[str]],
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        chunks = text_iterator(response, encoding=encoding)
        assert client.stats().active_requests == 1
        assert client.stats().response_body_aborted == 0
        with pytest.raises(foghttp.LifecycleError, match="consumed only once"):
            response.aiter_bytes()

        with pytest.raises(LookupError):
            await anext(chunks)

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="non-text override should abort the unread body exactly once",
        )
        await response.aclose()
        await response.aclose()
        assert client.stats().response_body_aborted == 1
        assert client.stats().active_requests == 0
