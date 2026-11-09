import asyncio

import pytest

from foghttp._upload_body.async_sending import send_async_upload_chunk
from tests.client_upload.helpers import ProgressRawBody


async def test_async_upload_progress_preserves_offsets_and_input_identity_across_backpressure() -> None:
    chunk = b"abcdef"
    raw_body = ProgressRawBody([2, 0, 3, 1])
    ready = asyncio.Event()
    task = asyncio.create_task(send_async_upload_chunk(raw_body, ready, chunk, final=True))
    await asyncio.wait_for(raw_body.backpressure.wait(), timeout=1)

    assert not task.done()
    assert [offset for _, offset, _ in raw_body.calls] == [0, 2]
    ready.set()
    assert await asyncio.wait_for(task, timeout=1) is True
    assert [offset for _, offset, _ in raw_body.calls] == [0, 2, 2, 5]
    assert all(content is chunk and final for content, _, final in raw_body.calls)
    assert raw_body.received == chunk


async def test_async_upload_progress_stops_after_partial_acceptance_when_closed() -> None:
    raw_body = ProgressRawBody([2, 0], close_on_backpressure=True)

    assert await asyncio.wait_for(send_async_upload_chunk(raw_body, asyncio.Event(), b"abcdef"), timeout=1) is False
    assert [offset for _, offset, _ in raw_body.calls] == [0, 2]
    assert raw_body.received == b"ab"


async def test_async_upload_progress_yields_to_cancellation_between_accepted_fragments() -> None:
    chunk = b"data" * 1024
    raw_body = ProgressRawBody([1] * len(chunk))
    task = asyncio.create_task(send_async_upload_chunk(raw_body, asyncio.Event(), chunk))

    async def cancel_after_first_fragment() -> None:
        await raw_body.first_accepted.wait()
        task.cancel()

    canceller = asyncio.create_task(cancel_after_first_fragment())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    await asyncio.wait_for(canceller, timeout=1)
    assert len(raw_body.calls) == 1
    assert raw_body.received == chunk[:1]
    await asyncio.sleep(0)
    assert len(raw_body.calls) == 1
