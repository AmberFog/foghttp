from functools import partial
import gzip
import io
import os
from pathlib import Path
import tempfile
from unittest.mock import Mock

import pytest

import foghttp
from foghttp._upload_body.file_source import FileUploadSource, file_content_length
from foghttp.methods import POST
from tests.client_upload.file_length_sources import (
    FILE_PAYLOAD,
    STANDARD_SOURCE_KINDS,
    ExpandingBytesIO,
    ExpandingFileIO,
    GuardedFile,
    buffered_write_source,
    expanding_readinto,
    standard_file,
)


@pytest.mark.parametrize("source_kind", STANDARD_SOURCE_KINDS)
@pytest.mark.parametrize("offset", [0, 3])
def test_standard_files_preserve_position_and_remaining_bytes(
    tmp_path: Path,
    source_kind: str,
    offset: int,
) -> None:
    with standard_file(tmp_path, source_kind) as source:
        source.read(offset)

        assert file_content_length(source) == len(FILE_PAYLOAD) - offset
        assert source.tell() == offset
        assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD[offset:]


def test_bytesio_length_keeps_buffer_resizable_and_closable() -> None:
    source = io.BytesIO(FILE_PAYLOAD)

    assert file_content_length(source) == len(FILE_PAYLOAD)
    source.seek(0, io.SEEK_END)
    source.write(b"extended")
    source.close()
    assert source.closed is True


@pytest.mark.parametrize("multipart", [False, True], ids=["content", "files"])
def test_request_construction_does_not_probe_generic_file(*, multipart: bool) -> None:
    source = GuardedFile()

    with foghttp.Client() as client:
        if multipart:
            client.build_request(POST, "https://example.test/upload", files={"file": ("payload.bin", source)})
        else:
            client.build_request(POST, "https://example.test/upload", content=source)

    assert source.read_calls == 0
    assert source.position == 0
    assert source.read() == FILE_PAYLOAD


@pytest.mark.parametrize("buffered", [False, True], ids=["gzip", "buffered-gzip"])
def test_compressed_raw_storage_does_not_define_reader_length(tmp_path: Path, *, buffered: bool) -> None:
    path = tmp_path / "compressed.gz"
    path.write_bytes(gzip.compress(FILE_PAYLOAD, mtime=0))

    with gzip.open(path, "rb") as compressed:
        source = io.BufferedReader(compressed) if buffered else compressed
        with source:
            assert file_content_length(source) is None
            assert source.tell() == 0
            assert source.read() == FILE_PAYLOAD


def test_bytesio_subclass_can_change_logical_length() -> None:
    with ExpandingBytesIO(FILE_PAYLOAD) as source:
        assert file_content_length(source) is None
        assert source.tell() == 0
        assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD * 2


@pytest.mark.parametrize("source_kind", STANDARD_SOURCE_KINDS)
def test_instance_read_override_is_not_assumed_to_preserve_storage_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    with standard_file(tmp_path, source_kind) as source:
        original_read = source.read
        monkeypatch.setattr(source, "read", lambda size=-1: original_read(size) * 2)

        assert file_content_length(source) is None
        assert source.tell() == 0
        assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD * 2


def test_buffered_reader_rejects_raw_instance_readinto_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "raw-override.bin"
    path.write_bytes(FILE_PAYLOAD)

    with path.open("rb", buffering=0) as raw:
        monkeypatch.setattr(raw, "readinto", partial(expanding_readinto, raw))
        with io.BufferedReader(raw) as source:
            assert file_content_length(source) is None
            assert source.tell() == 0
            assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD * 2


def test_buffered_reader_rejects_transforming_fileio_subclass(tmp_path: Path) -> None:
    path = tmp_path / "transforming-raw.bin"
    path.write_bytes(FILE_PAYLOAD)

    with ExpandingFileIO(path, "rb") as raw, io.BufferedReader(raw) as source:
        assert file_content_length(source) is None
        assert source.tell() == 0
        assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD * 2


def test_buffered_random_rejects_raw_write_override_before_read_flush(tmp_path: Path) -> None:
    with buffered_write_source(tmp_path / "write-override.bin") as source:
        assert file_content_length(source) is None
        assert source.raw.tell() == 0
        assert b"".join(FileUploadSource(source)) == FILE_PAYLOAD


def test_spooled_file_length_does_not_roll_over_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    with tempfile.SpooledTemporaryFile(mode="w+b") as source:
        source.write(FILE_PAYLOAD)
        source.seek(0)
        rollover = Mock(side_effect=AssertionError)
        monkeypatch.setattr(source, "rollover", rollover)

        assert file_content_length(source) is None
        assert source.tell() == 0
        assert source.read() == FILE_PAYLOAD
        rollover.assert_not_called()


def test_non_regular_raw_file_keeps_unknown_length() -> None:
    read_descriptor, write_descriptor = os.pipe()
    with io.FileIO(read_descriptor, "rb") as source, io.FileIO(write_descriptor, "wb") as writer:
        writer.write(FILE_PAYLOAD)
        writer.close()

        assert file_content_length(source) is None
        assert source.read() == FILE_PAYLOAD


@pytest.mark.parametrize("source_kind", STANDARD_SOURCE_KINDS)
def test_closed_standard_file_keeps_unknown_length(tmp_path: Path, source_kind: str) -> None:
    with standard_file(tmp_path, source_kind) as source:
        source.close()

        assert file_content_length(source) is None


def test_position_beyond_buffer_is_not_a_negative_length() -> None:
    with io.BytesIO(FILE_PAYLOAD) as source:
        source.seek(1, io.SEEK_END)

        assert file_content_length(source) is None
        assert source.read() == b""
