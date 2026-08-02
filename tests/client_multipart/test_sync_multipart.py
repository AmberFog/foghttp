import time
from typing import Any, cast

import pytest

import foghttp
from foghttp.messages import MULTIPART_FILES_UNSUPPORTED, SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED
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
    BlockingSyncChunks,
    ClosingBytesFile,
    NonRegularFilenoFile,
    SyncChunks,
    TrackedFactory,
)
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.transport_stats import wait_for_sync_transport_stats


EXPECTED_REPLAY_FACTORY_CALLS = 2
MULTIPART_FACTORY_FAILURE = "multipart factory failed"
MULTIPART_TOTAL_TIMEOUT = 3.0
MULTIPART_WRITE_TIMEOUT = 0.05
STALLED_PROVIDER_RETURN_LIMIT = 1.0


def test_sync_client_sends_multipart_files_and_form_fields(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            data={"description": "avatar", "tag": ["one", "two"]},
            files={"file": ("avatar.txt", b"payload", "text/plain")},
        )

    payload = response.json()
    assert payload["headers"]["content-type"][0].startswith("multipart/form-data; boundary=foghttp-")
    assert_multipart_parts(
        multipart_parts_from_payload(payload),
        [
            MultipartPart(name="description", content=b"avatar"),
            MultipartPart(name="tag", content=b"one"),
            MultipartPart(name="tag", content=b"two"),
            MultipartPart(
                name="file",
                filename="avatar.txt",
                content=b"payload",
                content_type="text/plain",
            ),
        ],
    )


def test_sync_client_streams_file_multipart_without_closing_external_file(sync_http_server: str) -> None:
    file_obj = ClosingBytesFile(b"file payload", name="reports/report.txt")

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files={"report": file_obj},
        )

    payload = response.json()
    assert payload["headers"]["content-length"]
    assert payload["headers"]["transfer-encoding"] == []
    assert file_obj.closed is False
    assert_multipart_parts(
        multipart_parts_from_payload(payload),
        [
            MultipartPart(
                name="report",
                filename="report.txt",
                content=b"file payload",
                content_type="application/octet-stream",
            ),
        ],
    )


def test_sync_client_streams_unknown_size_multipart_as_chunked(sync_http_server: str) -> None:
    stream = SyncChunks((b"first", b"second"))

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
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
                content=b"firstsecond",
                content_type="application/octet-stream",
            ),
        ],
    )


def test_sync_client_streams_tuple_byte_stream_multipart_as_chunked(sync_http_server: str) -> None:
    stream = (b"first", b"second")

    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files={"stream": stream},
        )

    payload = response.json()
    assert payload["headers"]["content-length"] == []
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert_multipart_parts(
        multipart_parts_from_payload(payload),
        [
            MultipartPart(
                name="stream",
                filename="stream",
                content=b"firstsecond",
                content_type="application/octet-stream",
            ),
        ],
    )


def test_sync_client_streams_non_regular_file_multipart_as_chunked(sync_http_server: str) -> None:
    with NonRegularFilenoFile(b"pipe-like", name="pipe.bin") as file_obj, foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files={"pipe": file_obj},
        )
        payload = response.json()
        assert file_obj.closed is False

    assert payload["headers"]["content-length"] == []
    assert payload["headers"]["transfer-encoding"] == ["chunked"]
    assert_multipart_parts(
        multipart_parts_from_payload(payload),
        [
            MultipartPart(
                name="pipe",
                filename="pipe.bin",
                content=b"pipe-like",
                content_type="application/octet-stream",
            ),
        ],
    )


def test_sync_client_sends_repeated_file_fields(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files=[
                ("file", ("first.txt", b"first")),
                ("file", ("second.txt", b"second")),
            ],
        )

    assert_multipart_parts(
        multipart_parts_from_payload(response.json()),
        [
            MultipartPart(
                name="file",
                filename="first.txt",
                content=b"first",
                content_type="application/octet-stream",
            ),
            MultipartPart(
                name="file",
                filename="second.txt",
                content=b"second",
                content_type="application/octet-stream",
            ),
        ],
    )


def test_sync_file_multipart_rejects_method_preserving_redirect(sync_http_server: str) -> None:
    source = ClosingBytesFile(b"not replayable")

    with (
        foghttp.Client(follow_redirects=True) as client,
        pytest.raises(foghttp.RequestError, match="non-replayable request body"),
    ):
        client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            files={"file": source},
        )

    assert source.close_calls == 0
    source.close()


def test_sync_buffered_multipart_replays_method_preserving_redirect(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
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


def test_sync_factory_multipart_replays_method_preserving_redirect(sync_http_server: str) -> None:
    sources: list[SyncChunks] = []

    def content() -> SyncChunks:
        source = SyncChunks((b"factory",))
        sources.append(source)
        return source

    factory = TrackedFactory(content)
    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
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


def test_sync_stream_response_accepts_multipart_upload(sync_http_server: str) -> None:
    with (
        foghttp.Client() as client,
        client.stream(
            POST,
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files={"file": ("payload.txt", b"stream-response")},
        ) as response,
    ):
        body = b"".join(response.iter_bytes())

    assert b"stream-response" in body


def test_sync_client_rejects_multipart_factory_returning_async_part(sync_http_server: str) -> None:
    sources: list[AsyncChunks] = []

    def async_part() -> AsyncChunks:
        source = AsyncChunks((b"not-sync",))
        sources.append(source)
        return source

    factory = TrackedFactory(async_part)
    with (
        foghttp.Client() as client,
        pytest.raises(TypeError, match=SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED),
    ):
        client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files=cast("Any", {"file": ("async.bin", factory)}),
        )

    assert factory.close_calls == 0
    assert sources[0].close_calls == 1


def test_sync_multipart_factory_returning_unsupported_source_fails_cleanly(sync_http_server: str) -> None:
    def invalid_part() -> object:
        return object()

    with foghttp.Client() as client:
        with pytest.raises(foghttp.RequestError, match=MULTIPART_FILES_UNSUPPORTED):
            client.post(
                f"{sync_http_server}{SECURITY_HEADERS_PATH}",
                files=cast("Any", {"file": ("invalid.bin", invalid_part)}),
            )
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart factory failure did not release request slot",
        )


def test_sync_multipart_closes_sources_when_later_factory_fails(sync_http_server: str) -> None:
    source = SyncChunks((b"opened",))
    first_factory = TrackedFactory(lambda: source)

    def failing_part() -> object:
        raise RuntimeError(MULTIPART_FACTORY_FAILURE)

    second_factory = TrackedFactory(failing_part)
    with foghttp.Client() as client, pytest.raises(RuntimeError, match=MULTIPART_FACTORY_FAILURE):
        client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files=[
                ("first", ("first.bin", first_factory)),
                ("second", ("second.bin", second_factory)),
            ],
        )

    assert first_factory.close_calls == 0
    assert second_factory.close_calls == 0
    assert source.close_calls == 1


def test_sync_multipart_closes_async_source_when_later_factory_fails(sync_http_server: str) -> None:
    source = AsyncChunks((b"opened",))
    first_factory = TrackedFactory(lambda: source)

    def failing_part() -> object:
        raise RuntimeError(MULTIPART_FACTORY_FAILURE)

    second_factory = TrackedFactory(failing_part)
    with foghttp.Client() as client, pytest.raises(RuntimeError, match=MULTIPART_FACTORY_FAILURE):
        client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files=cast(
                "Any",
                [
                    ("first", ("first.bin", first_factory)),
                    ("second", ("second.bin", second_factory)),
                ],
            ),
        )

    assert first_factory.close_calls == 0
    assert second_factory.close_calls == 0
    assert source.close_calls == 1


def test_sync_streaming_multipart_write_timeout_covers_stalled_provider(sync_http_server: str) -> None:
    source = BlockingSyncChunks((b"first", b"second"))

    started = time.perf_counter()
    with foghttp.Client(
        timeouts=foghttp.Timeouts(
            write=MULTIPART_WRITE_TIMEOUT,
            total=MULTIPART_TOTAL_TIMEOUT,
        ),
    ) as client:
        with pytest.raises(foghttp.WriteTimeout, match="request body write timeout expired") as exc_info:
            client.post(
                f"{sync_http_server}{SECURITY_HEADERS_PATH}",
                files={"file": ("slow.bin", source)},
            )
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="multipart write timeout did not release request slot",
        )
    elapsed = time.perf_counter() - started

    assert exc_info.value.phase == "request_body"
    assert elapsed < STALLED_PROVIDER_RETURN_LIMIT
    assert source.close_calls == 0
    source.close()
    assert source.finished.wait(STALLED_PROVIDER_RETURN_LIMIT)
