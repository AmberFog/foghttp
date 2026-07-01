from typing import Any, cast

import pytest

import foghttp
from foghttp.messages import SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED
from foghttp.methods import POST
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.client_multipart.assertions import (
    assert_multipart_parts,
    multipart_parts_from_payload,
    parse_multipart_parts,
)
from tests.client_multipart.models import MultipartPart
from tests.client_multipart.sources import AsyncChunks, ClosingBytesFile, NonRegularFilenoFile, SyncChunks
from tests.redirect_helpers import SECURITY_HEADERS_PATH


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
    with (
        foghttp.Client(follow_redirects=True) as client,
        pytest.raises(foghttp.RequestError, match="non-replayable request body"),
    ):
        client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            files={"file": ClosingBytesFile(b"not replayable")},
        )


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
    def async_part() -> AsyncChunks:
        return AsyncChunks((b"not-sync",))

    with (
        foghttp.Client() as client,
        pytest.raises(TypeError, match=SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED),
    ):
        client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            files=cast("Any", {"file": ("async.bin", async_part)}),
        )
