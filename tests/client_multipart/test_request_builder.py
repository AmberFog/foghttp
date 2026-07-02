import io
from typing import TYPE_CHECKING, Any, cast

import pytest

import foghttp
from foghttp._request_body import request_body
from foghttp.messages import (
    BODY_PARAMETER_CONFLICT,
    MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED,
    MULTIPART_CONTENT_TYPE_UNSUPPORTED,
    MULTIPART_DATA_UNSUPPORTED,
    MULTIPART_FILES_UNSUPPORTED,
    MULTIPART_HEADER_VALUE_UNSUPPORTED,
)
from foghttp.methods import POST
from tests.client_multipart.assertions import assert_multipart_parts, parse_multipart_parts
from tests.client_multipart.models import MultipartPart
from tests.client_multipart.sources import ClosingBytesFile, SyncChunks


if TYPE_CHECKING:
    from foghttp.types import SyncMultipartFiles


def test_build_request_creates_buffered_replayable_multipart_body() -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            data={"description": "avatar"},
            files={"file": ("avatar.txt", b"payload", "text/plain")},
        )

    body = request_body(request)
    assert body.content is not None
    assert body.stream is None
    assert body.replayable is True
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=foghttp-")
    assert_multipart_parts(
        parse_multipart_parts(
            content_type=request.headers["content-type"],
            body=body.content,
        ),
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


@pytest.mark.parametrize("files", [{}, []])
def test_build_request_empty_files_creates_empty_multipart_body(files: object) -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            files=cast("Any", files),
        )

    body = request_body(request)
    assert body.content is not None
    assert body.stream is None
    assert body.replayable is True
    assert (
        parse_multipart_parts(
            content_type=request.headers["content-type"],
            body=body.content,
        )
        == []
    )


def test_build_request_empty_files_with_data_creates_multipart_fields() -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            data={"field": "value"},
            files={},
        )

    body = request_body(request)
    assert body.content is not None
    assert_multipart_parts(
        parse_multipart_parts(
            content_type=request.headers["content-type"],
            body=body.content,
        ),
        [MultipartPart(name="field", content=b"value")],
    )


def test_build_request_keeps_file_multipart_streaming_and_non_replayable() -> None:
    file_obj = ClosingBytesFile(b"file payload", name="reports/report.txt")

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            files={"report": file_obj},
        )

    body = request_body(request)
    assert request.content is None
    assert body.stream is not None
    assert body.replayable is False
    assert body.content_length is not None
    assert file_obj.closed is False


def test_build_request_creates_replayable_multipart_stream_for_factories() -> None:
    def content() -> SyncChunks:
        return SyncChunks((b"first", b"second"))

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            files={"stream": ("stream.bin", content)},
        )

    body = request_body(request)
    assert request.content is None
    assert body.stream is not None
    assert body.replayable is True
    assert body.content_length is None


def test_build_request_rejects_file_factories_mixed_with_direct_streams() -> None:
    def content() -> SyncChunks:
        return SyncChunks((b"fresh",))

    files: SyncMultipartFiles = [
        ("direct", ("direct.bin", io.BytesIO(b"direct"))),
        ("factory", ("factory.bin", content)),
    ]

    with foghttp.Client() as client, pytest.raises(TypeError, match="file factories cannot be mixed"):
        client.build_request(
            POST,
            "https://api.example/upload",
            files=files,
        )


@pytest.mark.parametrize(
    "body_kwargs",
    [
        {"content": b"raw", "files": {"file": b"payload"}},
        {"json": {"name": "Ada"}, "files": {"file": b"payload"}},
        {"content": b"raw", "json": {"name": "Ada"}, "files": {"file": b"payload"}},
    ],
)
def test_build_request_rejects_files_with_incompatible_body_sources(body_kwargs: dict[str, object]) -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
        client.build_request(POST, "https://api.example/upload", **cast("Any", body_kwargs))


@pytest.mark.parametrize("data", [b"raw=data", "raw=data"])
def test_build_request_rejects_raw_data_with_files(data: object) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=MULTIPART_DATA_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            data=data,  # type: ignore[arg-type]
            files={"file": b"payload"},
        )


@pytest.mark.parametrize(
    "files",
    [
        {"field\r\nx": b"payload"},
        {"field\x00x": b"payload"},
        {"field\x1fx": b"payload"},
        {"field\x7fx": b"payload"},
        {"field\u202ex": b"payload"},
        {"field": ("name\r\nx.txt", b"payload")},
        {"field": ("name.txt", b"payload", "text/plain\x00")},
        {"field": ("name.txt", b"payload", "text/plain\r\nx: y")},
    ],
)
def test_build_request_rejects_multipart_header_injection(files: object) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        client.build_request(POST, "https://api.example/upload", files=cast("Any", files))


@pytest.mark.parametrize(
    "files",
    [
        {"fiéld": b"payload"},
        {"field": ("café.txt", b"payload")},
        {"field": ("name.txt", b"payload", "text/pläin")},
    ],
)
def test_rejects_non_ascii_multipart_headers(files: object) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        client.build_request(POST, "https://api.example/upload", files=cast("Any", files))


def test_build_request_rejects_unsafe_data_field_name() -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=MULTIPART_DATA_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            data={"name\r\nx": "value"},
            files={"file": b"payload"},
        )


def test_build_request_rejects_custom_multipart_content_type() -> None:
    content_type = "multipart/custom"

    with foghttp.Client() as client, pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": content_type},
            files={"file": b"payload"},
        )


def test_build_request_preserves_explicit_form_data_parameters_with_quoted_semicolon() -> None:
    content_type = 'multipart/form-data; charset="a;b"'

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": content_type},
            files={"file": b"payload"},
        )

    assert request.headers["content-type"].startswith('multipart/form-data; charset="a;b"; boundary=foghttp-')


def test_build_request_preserves_escaped_explicit_form_data_parameter() -> None:
    content_type = 'multipart/form-data; note="a\\"b"'

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": content_type},
            files={"file": b"payload"},
        )

    assert request.headers["content-type"].startswith('multipart/form-data; note="a\\"b"; boundary=foghttp-')


def test_build_request_rejects_non_multipart_content_type_with_files() -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": "application/octet-stream"},
            files={"file": b"payload"},
        )


def test_build_request_rejects_explicit_multipart_boundary() -> None:
    with (
        foghttp.Client() as client,
        pytest.raises(
            ValueError,
            match=MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED,
        ),
    ):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": "multipart/form-data; boundary=caller"},
            files={"file": b"payload"},
        )


def test_build_request_rejects_quoted_explicit_multipart_boundary() -> None:
    with (
        foghttp.Client() as client,
        pytest.raises(
            ValueError,
            match=MULTIPART_CONTENT_TYPE_BOUNDARY_UNSUPPORTED,
        ),
    ):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": 'multipart/form-data; boundary="caller"'},
            files={"file": b"payload"},
        )


def test_build_request_rejects_malformed_multipart_content_type_parameter() -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": 'multipart/form-data; charset="unterminated'},
            files={"file": b"payload"},
        )


def test_build_request_rejects_multipart_content_type_trailing_escape() -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": 'multipart/form-data; note="unterminated\\'},
            files={"file": b"payload"},
        )


def test_build_request_rejects_unsafe_multipart_content_type() -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=MULTIPART_HEADER_VALUE_UNSUPPORTED):
        client.build_request(
            POST,
            "https://api.example/upload",
            headers={"content-type": "multipart/form-data\r\nx: y"},
            files={"file": b"payload"},
        )
