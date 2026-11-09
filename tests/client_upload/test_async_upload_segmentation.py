import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_multipart.sources import FailsWhenReadPastExactLengthFile
from tests.client_upload.upload_segmentation_cases import (
    RECOVERY_UPLOAD,
    SEGMENTATION_PAYLOAD,
    UPLOAD_GATE_TIMEOUT,
    AsyncSnapshotGate,
    MutableUploadChunk,
    assert_segmented_upload,
    async_upload_chunks,
    upload_request_options,
)
from tests.redirect_helpers import SECURITY_HEADERS_PATH
from tests.support.upload_requests import known_length_upload_request


@pytest.mark.parametrize("upload_mode", ["content", "multipart"])
async def test_async_oversized_logical_chunk_preserves_payload_and_releases_budget(
    http_server: str,
    segmentation_limits: foghttp.Limits,
    upload_mode: str,
) -> None:
    url = f"{http_server}{SECURITY_HEADERS_PATH}"
    options = upload_request_options(async_upload_chunks(SEGMENTATION_PAYLOAD), upload_mode)

    async with foghttp.AsyncClient(limits=segmentation_limits) as client:
        response = await client.post(url, **options)
        recovery = await client.post(url, content=async_upload_chunks(RECOVERY_UPLOAD))
        stats = client.stats()

    assert response.status_code == OK
    assert_segmented_upload(response.json(), SEGMENTATION_PAYLOAD, upload_mode)
    assert recovery.status_code == OK
    assert_segmented_upload(recovery.json(), RECOVERY_UPLOAD, "content")
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


@pytest.mark.parametrize("upload_mode", ["content", "multipart"])
async def test_async_mutable_chunk_is_snapshotted_before_segmented_sending(
    http_server: str,
    segmentation_limits: foghttp.Limits,
    upload_mode: str,
    mutable_upload_chunk: MutableUploadChunk,
    async_upload_snapshot: AsyncSnapshotGate,
) -> None:
    url = f"{http_server}{SECURITY_HEADERS_PATH}"
    options = upload_request_options(async_upload_chunks(mutable_upload_chunk.chunk), upload_mode)

    async with foghttp.AsyncClient(limits=segmentation_limits) as client:
        request = asyncio.create_task(client.post(url, **options))
        try:
            await asyncio.wait_for(async_upload_snapshot.captured.wait(), timeout=UPLOAD_GATE_TIMEOUT)
            mutable_upload_chunk.mutate()
        finally:
            async_upload_snapshot.release.set()
        response = await asyncio.wait_for(request, timeout=UPLOAD_GATE_TIMEOUT)

    assert response.status_code == OK
    assert_segmented_upload(response.json(), SEGMENTATION_PAYLOAD, upload_mode)
    assert bytes(mutable_upload_chunk.backing) != SEGMENTATION_PAYLOAD


async def test_async_segmented_final_chunk_preserves_known_length_without_extra_source_read(
    http_server: str,
    segmentation_limits: foghttp.Limits,
) -> None:
    payload = SEGMENTATION_PAYLOAD[:32_787]
    source = FailsWhenReadPastExactLengthFile(payload)

    async with foghttp.AsyncClient(limits=segmentation_limits) as client:
        request = known_length_upload_request(
            client,
            f"{http_server}{SECURITY_HEADERS_PATH}",
            source,
            len(payload),
        )
        response = await client.send(request)

    received = response.json()
    assert response.status_code == OK
    assert received["body"].encode() == payload
    assert received["headers"]["content-length"] == [str(len(payload))]
    assert received["headers"]["transfer-encoding"] == []
    assert source.read_past_declared_body is False
    assert source.close_calls == 1
