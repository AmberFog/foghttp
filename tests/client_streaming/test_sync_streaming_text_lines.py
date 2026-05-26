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
from tests.client_streaming.server import SyncStreamingServer
from tests.client_streaming.stream_readers import append_sync_stream_items, fail_on_sync_stream_items
from tests.support.transport_stats import wait_for_sync_transport_stats


def test_sync_stream_iter_text_decodes_multibyte_boundaries(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert "".join(response.iter_text()) == TEXT_LINES_BODY


def test_sync_stream_iter_text_uses_charset_header(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{LATIN1_TEXT_STREAM_PATH}") as response,
    ):
        assert response.encoding == "iso-8859-1"
        assert "".join(response.iter_text()) == LATIN1_TEXT_VALUE


def test_sync_stream_iter_lines_handles_chunk_boundaries(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert list(response.iter_lines()) == list(TEXT_LINES)


def test_sync_stream_body_can_be_consumed_only_once(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert list(response.iter_lines()) == list(TEXT_LINES)

        with pytest.raises(foghttp.LifecycleError, match="consumed only once"):
            response.iter_bytes()


def test_sync_stream_invalid_line_limit_does_not_consume_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(ValueError, match="max_line_chars"):
            response.iter_lines(max_line_chars=0)

        assert list(response.iter_lines()) == list(TEXT_LINES)


def test_sync_stream_invalid_text_encoding_aborts_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(LookupError):
            next(response.iter_text(encoding="foghttp-unknown-codec"))

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="invalid stream text encoding should abort the unread body",
        )


def test_sync_stream_overlong_line_aborts_body(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        with pytest.raises(foghttp.ResponseError, match="max_line_chars=4"):
            list(response.iter_lines(max_line_chars=4))

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="overlong stream line should abort the body",
        )


def test_sync_stream_iter_text_preserves_text_before_tail_error(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    collected_text: list[str] = []
    with (
        foghttp.Client() as client,
        client.stream(
            GET,
            f"{sync_streaming_server.base_url}{BROKEN_READY_TAIL_STREAM_PATH}",
        ) as response,
        pytest.raises(foghttp.RequestError),
    ):
        append_sync_stream_items(response.iter_text(), collected_text)

    assert "".join(collected_text) == (FIRST_CHUNK + SECOND_CHUNK).decode()


def test_sync_stream_iter_lines_does_not_flush_partial_line_after_error(
    sync_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(
            GET,
            f"{sync_streaming_server.base_url}{BROKEN_READY_TAIL_STREAM_PATH}",
        ) as response,
        pytest.raises(foghttp.RequestError),
    ):
        fail_on_sync_stream_items(
            response.iter_lines(),
            "partial line should not be flushed before stream error: {item!r}",
        )
