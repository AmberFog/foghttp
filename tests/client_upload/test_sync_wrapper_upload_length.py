from pathlib import Path

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_upload.wrapper_length_cases import (
    WRAPPER_SOURCE_KINDS,
    assert_received_content,
    assert_received_multipart,
    wrapper_length_case,
)
from tests.redirect_helpers import SECURITY_HEADERS_PATH


@pytest.mark.parametrize("source_kind", WRAPPER_SOURCE_KINDS)
def test_sync_content_preserves_reader_payload(
    sync_http_server: str,
    tmp_path: Path,
    source_kind: str,
) -> None:
    with wrapper_length_case(tmp_path, source_kind) as case, foghttp.Client() as client:
        response = client.post(f"{sync_http_server}{SECURITY_HEADERS_PATH}", content=case.source)

        assert response.status_code == OK
        assert_received_content(response.json(), case)
        assert len(case.opened) == 1
        assert all(source.closed for source in case.opened)


@pytest.mark.parametrize("source_kind", WRAPPER_SOURCE_KINDS)
def test_sync_multipart_preserves_reader_payload_and_closing_boundary(
    sync_http_server: str,
    tmp_path: Path,
    source_kind: str,
) -> None:
    with wrapper_length_case(tmp_path, source_kind) as case, foghttp.Client() as client:
        response = client.post(
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            data={"description": "wrapper length"},
            files={"file": ("payload.bin", case.source)},
        )

        assert response.status_code == OK
        assert_received_multipart(response.json(), case)
        assert len(case.opened) == 1
        assert all(source.closed is case.factory_owned for source in case.opened)
