from collections.abc import Callable, Iterator

import pytest

import foghttp
from foghttp.methods import GET
from tests.client_streaming.constants import (
    BOM_TEXT_STREAM_CHUNKS,
    TEXT_LINES,
    TEXT_LINES_BODY,
    TEXT_LINES_STREAM_PATH,
)
from tests.client_streaming.server import SyncStreamingServer
from tests.client_streaming.text_codec_cases import NON_TEXT_CODECS, NON_TEXT_CONTENT_TYPES
from tests.support.transport_stats import wait_for_sync_transport_stats


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
def test_sync_non_text_charset_falls_back_without_sniffing_stream_bom(
    sync_codec_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert response.encoding == "utf-8"
        assert client.stats().active_requests == 1
        chunks = list(response.iter_text())

        assert all(isinstance(chunk, str) for chunk in chunks)
        assert "".join(chunks) == "\ufeff" + TEXT_LINES_BODY


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
def test_sync_non_text_charset_lines_are_text(
    sync_codec_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        lines = list(response.iter_lines())

        assert all(isinstance(line, str) for line in lines)
        assert lines == ["\ufeff" + TEXT_LINES[0], *TEXT_LINES[1:]]


@pytest.mark.parametrize("content_type", NON_TEXT_CONTENT_TYPES, ids=NON_TEXT_CODECS)
def test_sync_non_text_charset_preserves_raw_bytes(
    sync_codec_streaming_server: SyncStreamingServer,
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_codec_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        assert b"".join(response.iter_bytes()) == b"".join(BOM_TEXT_STREAM_CHUNKS)


@pytest.mark.parametrize("encoding", NON_TEXT_CODECS)
@pytest.mark.parametrize(
    "text_iterator",
    [
        pytest.param(foghttp.StreamResponse.iter_text, id="text"),
        pytest.param(foghttp.StreamResponse.iter_lines, id="lines"),
    ],
)
def test_sync_non_text_override_fails_lazily_and_aborts_once(
    sync_streaming_server: SyncStreamingServer,
    encoding: str,
    text_iterator: Callable[..., Iterator[str]],
) -> None:
    with (
        foghttp.Client() as client,
        client.stream(GET, f"{sync_streaming_server.base_url}{TEXT_LINES_STREAM_PATH}") as response,
    ):
        chunks = text_iterator(response, encoding=encoding)
        assert client.stats().active_requests == 1
        assert client.stats().response_body_aborted == 0
        with pytest.raises(foghttp.LifecycleError, match="consumed only once"):
            response.iter_bytes()

        with pytest.raises(LookupError):
            next(chunks)

        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.response_body_aborted == 1,
            message="non-text override should abort the unread body exactly once",
        )
        response.close()
        response.close()
        assert client.stats().response_body_aborted == 1
        assert client.stats().active_requests == 0
