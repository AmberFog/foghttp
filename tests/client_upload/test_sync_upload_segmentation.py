from concurrent.futures import ThreadPoolExecutor

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_multipart.sources import FailsWhenReadPastExactLengthFile
from tests.client_upload.upload_segmentation_cases import (
    RECOVERY_UPLOAD,
    SEGMENTATION_PAYLOAD,
    UPLOAD_GATE_TIMEOUT,
    MutableUploadChunk,
    SyncSnapshotGate,
    assert_segmented_upload,
    upload_request_options,
)
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.upload_requests import known_length_upload_request


@pytest.mark.parametrize("upload_mode", ["content", "multipart"])
def test_sync_oversized_logical_chunk_preserves_payload_and_releases_budget(
    sync_http_server: str,
    segmentation_limits: foghttp.Limits,
    upload_mode: str,
) -> None:
    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    options = upload_request_options(iter((SEGMENTATION_PAYLOAD,)), upload_mode)

    with foghttp.Client(limits=segmentation_limits) as client:
        response = client.post(url, **options)
        recovery = client.post(url, content=iter((RECOVERY_UPLOAD,)))
        stats = client.stats()

    assert response.status_code == OK
    assert_segmented_upload(response.json(), SEGMENTATION_PAYLOAD, upload_mode)
    assert recovery.status_code == OK
    assert_segmented_upload(recovery.json(), RECOVERY_UPLOAD, "content")
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


@pytest.mark.parametrize("upload_mode", ["content", "multipart"])
def test_sync_mutable_chunk_is_snapshotted_before_segmented_sending(
    sync_http_server: str,
    segmentation_limits: foghttp.Limits,
    upload_mode: str,
    mutable_upload_chunk: MutableUploadChunk,
    sync_upload_snapshot: SyncSnapshotGate,
) -> None:
    url = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    options = upload_request_options(iter((mutable_upload_chunk.chunk,)), upload_mode)

    with foghttp.Client(limits=segmentation_limits) as client, ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(client.post, url, **options)
        try:
            assert sync_upload_snapshot.captured.wait(UPLOAD_GATE_TIMEOUT)
            mutable_upload_chunk.mutate()
        finally:
            sync_upload_snapshot.release.set()
        response = request.result(timeout=UPLOAD_GATE_TIMEOUT)

    assert response.status_code == OK
    assert_segmented_upload(response.json(), SEGMENTATION_PAYLOAD, upload_mode)
    assert bytes(mutable_upload_chunk.backing) != SEGMENTATION_PAYLOAD


def test_sync_segmented_final_chunk_preserves_known_length_without_extra_source_read(
    sync_http_server: str,
    segmentation_limits: foghttp.Limits,
) -> None:
    payload = SEGMENTATION_PAYLOAD[:32_787]
    source = FailsWhenReadPastExactLengthFile(payload)

    with foghttp.Client(limits=segmentation_limits) as client:
        request = known_length_upload_request(
            client,
            f"{sync_http_server}{SECURITY_HEADERS_PATH}",
            source,
            len(payload),
        )
        response = client.send(request)

    received = response.json()
    assert response.status_code == OK
    assert received["body"].encode() == payload
    assert received["headers"]["content-length"] == [str(len(payload))]
    assert received["headers"]["transfer-encoding"] == []
    assert source.read_past_declared_body is False
    assert source.close_calls == 1
