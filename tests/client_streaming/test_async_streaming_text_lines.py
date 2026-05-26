import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming.constants import (
    BROKEN_READY_TAIL_STREAM_PATH,
    FIRST_CHUNK,
    LATIN1_TEXT_STREAM_PATH,
    LATIN1_TEXT_VALUE,
    SECOND_CHUNK,
    TEXT_LINES,
    TEXT_LINES_BODY,
    TEXT_LINES_STREAM_PATH,
)
from tests.client_streaming.server import AsyncStreamingServer
from tests.client_streaming.stream_readers import append_stream_items, fail_on_stream_items
from tests.support.transport_stats import wait_for_async_transport_stats


async def test_stream_aiter_text_decodes_multibyte_boundaries(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert "".join([chunk async for chunk in response.aiter_text()]) == TEXT_LINES_BODY


async def test_stream_aiter_text_uses_charset_header(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{LATIN1_TEXT_STREAM_PATH}") as response,
    ):
        assert response.encoding == "iso-8859-1"
        assert "".join([chunk async for chunk in response.aiter_text()]) == LATIN1_TEXT_VALUE


async def test_stream_aiter_lines_handles_chunk_boundaries(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert [line async for line in response.aiter_lines()] == list(TEXT_LINES)


async def test_stream_body_can_be_consumed_only_once(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert [line async for line in response.aiter_lines()] == list(TEXT_LINES)

        with pytest.raises(foghttp.LifecycleError, match="consumed only once"):
            response.aiter_bytes()


async def test_stream_invalid_line_limit_does_not_consume_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(ValueError, match="max_line_chars"):
            response.aiter_lines(max_line_chars=0)

        assert [line async for line in response.aiter_lines()] == list(TEXT_LINES)


async def test_stream_invalid_text_encoding_aborts_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(LookupError):
            await anext(response.aiter_text(encoding="foghttp-unknown-codec"))

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="invalid stream text encoding should abort the unread body",
        )


async def test_stream_overlong_line_aborts_body(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(GET, f"{streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
            [line async for line in response.aiter_lines(max_line_chars=4)]

        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="overlong stream line should abort the body",
        )


async def test_stream_aiter_text_preserves_text_before_tail_error(
    streaming_server: AsyncStreamingServer,
) -> None:
    collected_text: list[str] = []
    async with (
        foghttp.AsyncClient() as client,
        client.stream(
            GET,
            f"{streaming_server.base_url}{BROKEN_READY_TAIL_STREAM_PATH}",
        ) as response,
    ):
        with pytest.raises(foghttp.RequestError):
            await append_stream_items(response.aiter_text(), collected_text)

    assert "".join(collected_text) == (FIRST_CHUNK + SECOND_CHUNK).decode()


async def test_stream_aiter_lines_does_not_flush_partial_line_after_error(
    streaming_server: AsyncStreamingServer,
) -> None:
    async with (
        foghttp.AsyncClient() as client,
        client.stream(
            GET,
            f"{streaming_server.base_url}{BROKEN_READY_TAIL_STREAM_PATH}",
        ) as response,
    ):
        with pytest.raises(foghttp.RequestError):
            await fail_on_stream_items(
                response.aiter_lines(),
                "partial line should not be flushed before stream error: {item!r}",
            )
