import asyncio

import pytest

from foghttp._multipart.cleanup import MultipartFileCleanup
from foghttp._multipart.iterators import aiter_sync_file_content
from foghttp._multipart.models import MultipartFile
from foghttp._upload_body import cleanup
from foghttp._upload_body.cleanup_owner import CleanupOwner
from tests.client_multipart.sources import BlockingSyncChunks

from .cleanup_actions import wait_sync_event
from .constants import CALLBACK_WATCHDOG, COMPLETION_WATCHDOG
from .sources import SyncCloseGate


async def test_early_close_retires_only_the_multipart_wrapper_while_cleanup_is_busy(
    isolated_cleanup_owner: CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", CALLBACK_WATCHDOG)
    part = BlockingSyncChunks((b"first",))
    file = MultipartFile(
        "file",
        "payload",
        part,
        "application/octet-stream",
        None,
        replayable=False,
        async_source=False,
    )
    part_owner = MultipartFileCleanup(file)
    stream = aiter_sync_file_content(file, part_owner)
    assert await anext(stream) == b"first"
    gate = SyncCloseGate()
    blocked = isolated_cleanup_owner.reserve(1).submit_sync(gate.close)
    closing = asyncio.ensure_future(stream.aclose())
    try:
        assert await wait_sync_event(gate.entered)
        done, _pending = await asyncio.wait((closing,), timeout=COMPLETION_WATCHDOG)
        assert closing in done
        closing.result()
        assert not part.finished.is_set()
    finally:
        gate.release.set()
        await asyncio.wrap_future(blocked)
        await closing
        await part_owner.aclose()

    assert part.finished.is_set()
    assert part.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
