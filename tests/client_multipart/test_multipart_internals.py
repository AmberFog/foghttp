import threading

import pytest

from foghttp._multipart.length import multipart_content_length
from foghttp._multipart.models import MultipartField, MultipartFile, MultipartPayload
from foghttp._multipart.normalize import normalize_multipart_body
from foghttp._multipart.parts import multipart_payload
from foghttp._multipart.stream import (
    AsyncMultipartStream,
    MultipartStream,
    MultipartStreamFactory,
)
from foghttp._upload_body.chunks import body_chunk
from foghttp.messages import (
    MULTIPART_CONTENT_TYPE_UNSUPPORTED,
    MULTIPART_FILES_UNSUPPORTED,
    STREAMING_BODY_CHUNK_UNSUPPORTED,
)
from tests.client_multipart.sources import AsyncChunks, SyncChunks, ThreadTrackingSyncChunks


def test_body_chunk_accepts_mutable_bytes_like_values() -> None:
    assert body_chunk(bytearray(b"payload")) == b"payload"
    assert body_chunk(memoryview(b"payload")) == b"payload"


def test_body_chunk_rejects_text_chunks() -> None:
    with pytest.raises(TypeError, match=STREAMING_BODY_CHUNK_UNSUPPORTED):
        body_chunk("payload")


def test_normalize_multipart_body_rejects_empty_content_type() -> None:
    with pytest.raises(ValueError, match=MULTIPART_CONTENT_TYPE_UNSUPPORTED):
        normalize_multipart_body(
            data=None,
            files={"file": b"payload"},
            headers={"content-type": " ; "},
        )


def test_multipart_payload_accepts_bytes_form_fields_without_files() -> None:
    payload = multipart_payload(
        boundary="boundary",
        data={"field": b"raw"},
        files=None,
    )

    assert payload.fields == (MultipartField(name="field", content=b"raw"),)
    assert payload.files == ()


def test_multipart_payload_rejects_unsupported_file_content() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": object()},
        )


def test_multipart_payload_rejects_empty_filename() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": ("", b"payload")},
        )


def test_multipart_payload_rejects_non_string_file_field_name() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={1: b"payload"},
        )


def test_multipart_payload_rejects_unsafe_content_type() -> None:
    with pytest.raises(TypeError, match=MULTIPART_FILES_UNSUPPORTED):
        multipart_payload(
            boundary="boundary",
            data=None,
            files={"file": ("payload.bin", b"payload", "text/plain\r\nx: y")},
        )


def test_multipart_stream_closes_owned_sync_source() -> None:
    source = SyncChunks((b"payload",))
    stream = MultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
            ),
        ),
    )

    assert b"payload" in b"".join(stream)
    stream.close()
    assert source.closed is True


def test_multipart_stream_emits_exact_wire_bytes_for_field_and_file() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(MultipartField(name="description", content=b"avatar"),),
        files=(
            MultipartFile(
                name="file",
                filename="avatar.txt",
                content=b"payload",
                content_type="text/plain",
                content_length=len(b"payload"),
                replayable=True,
                async_source=False,
            ),
        ),
    )

    assert b"".join(MultipartStream(payload)) == (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="description"\r\n'
        b"\r\n"
        b"avatar\r\n"
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="file"; filename="avatar.txt"\r\n'
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"payload\r\n"
        b"--boundary--\r\n"
    )


def test_multipart_stream_escapes_quoted_header_parameters() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name='field"name',
                filename='path\\file"name.txt',
                content=b"",
                content_type="application/octet-stream",
                content_length=0,
                replayable=True,
                async_source=False,
            ),
        ),
    )

    assert b"".join(MultipartStream(payload)) == (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="field\\"name"; '
        b'filename="path\\\\file\\"name.txt"\r\n'
        b"Content-Type: application/octet-stream\r\n"
        b"\r\n"
        b"\r\n"
        b"--boundary--\r\n"
    )


async def test_async_multipart_stream_iterates_sync_and_async_sources() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(MultipartField(name="field", content=b"value"),),
        files=(
            MultipartFile(
                name="sync",
                filename="sync.bin",
                content=SyncChunks((b"sync",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
            MultipartFile(
                name="async",
                filename="async.bin",
                content=AsyncChunks((b"async",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=True,
            ),
        ),
    )

    body = b"".join([chunk async for chunk in AsyncMultipartStream(payload)])

    assert b"value" in body
    assert b"sync" in body
    assert b"async" in body


async def test_async_multipart_stream_reads_sync_parts_off_event_loop() -> None:
    sync_source = ThreadTrackingSyncChunks((b"sync",))
    loop_thread_id = threading.get_ident()
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="sync",
                filename="sync.bin",
                content=sync_source,
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
            MultipartFile(
                name="async",
                filename="async.bin",
                content=AsyncChunks((b"async",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=True,
            ),
        ),
    )

    body = b"".join([chunk async for chunk in AsyncMultipartStream(payload)])

    assert b"sync" in body
    assert sync_source.thread_ids
    assert loop_thread_id not in sync_source.thread_ids


async def test_async_multipart_stream_closes_owned_async_source() -> None:
    source = AsyncChunks((b"payload",))
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=True,
                    close_source=True,
                ),
            ),
        ),
    )

    await stream.aclose()
    assert source.closed is True


async def test_async_multipart_stream_closes_owned_sync_source() -> None:
    source = SyncChunks((b"payload",))
    stream = AsyncMultipartStream(
        MultipartPayload(
            boundary="boundary",
            fields=(),
            files=(
                MultipartFile(
                    name="file",
                    filename="payload.bin",
                    content=source,
                    content_type="application/octet-stream",
                    content_length=None,
                    replayable=False,
                    async_source=False,
                    close_source=True,
                ),
            ),
        ),
    )

    await stream.aclose()
    assert source.closed is True


def test_multipart_stream_factory_creates_fresh_sync_stream() -> None:
    payload = _factory_payload(lambda: SyncChunks((b"sync",)))

    stream = MultipartStreamFactory(payload)()

    assert isinstance(stream, MultipartStream)
    assert b"sync" in b"".join(stream)


async def test_multipart_stream_factory_creates_fresh_async_stream() -> None:
    payload = _factory_payload(lambda: AsyncChunks((b"async",)))

    stream = MultipartStreamFactory(payload)()

    assert isinstance(stream, AsyncMultipartStream)
    assert b"async" in b"".join([chunk async for chunk in stream])


def test_multipart_content_length_is_unknown_for_stream_part() -> None:
    payload = MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="file",
                filename="payload.bin",
                content=SyncChunks((b"payload",)),
                content_type="application/octet-stream",
                content_length=None,
                replayable=False,
                async_source=False,
            ),
        ),
    )

    assert multipart_content_length(payload) is None


def _factory_payload(factory: object) -> MultipartPayload:
    return MultipartPayload(
        boundary="boundary",
        fields=(),
        files=(
            MultipartFile(
                name="file",
                filename="payload.bin",
                content=factory,
                content_type="application/octet-stream",
                content_length=None,
                replayable=True,
                async_source=False,
                source_factory=True,
            ),
        ),
    )
