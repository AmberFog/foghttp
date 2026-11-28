import asyncio
from functools import partial
import threading

import pytest

from foghttp._multipart.cleanup import MultipartFileCleanup
from foghttp._multipart.models import MultipartFile
from foghttp._upload_body import cleanup

from .constants import CALLBACK_WATCHDOG, COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


def _part(source: object, *, asynchronous: bool) -> MultipartFileCleanup:
    file = MultipartFile(
        "file",
        "payload",
        source,
        "application/octet-stream",
        None,
        replayable=False,
        async_source=asynchronous,
        close_source=True,
    )
    return MultipartFileCleanup(file)


@pytest.mark.parametrize("multipart", [False, True], ids=["upload", "multipart"])
def test_sync_cleanup_propagates_an_interrupted_wait(
    monkeypatch: pytest.MonkeyPatch,
    *,
    multipart: bool,
) -> None:
    source = SyncCloseGate()
    owner = _part(source, asynchronous=False) if multipart else cleanup.UploadSourceCleanup(source)
    close = partial(owner.close, preserve_error=True) if isinstance(owner, MultipartFileCleanup) else owner.close
    completion = owner.start_sync_cleanup()
    assert completion is not None
    interruption = KeyboardInterrupt()
    waiting_thread = threading.current_thread()
    original_wait = threading.Condition.wait

    def interrupt_wait(condition: threading.Condition, timeout: float | None = None) -> bool:
        if threading.current_thread() is waiting_thread:
            raise interruption
        return original_wait(condition, timeout)

    def close_during_failure() -> None:
        try:
            raise ValueError
        finally:
            close()

    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        with monkeypatch.context() as patch:
            patch.setattr(threading.Condition, "wait", interrupt_wait)
            with pytest.raises(KeyboardInterrupt) as caught:
                close_during_failure()
            assert caught.value is interruption
        assert completion.done() is False
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1


async def test_multipart_cleanup_wait_propagates_caller_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", CALLBACK_WATCHDOG)
    source = AsyncCloseGate()
    owner = _part(source, asynchronous=True)

    async def close_during_failure() -> None:
        try:
            raise ValueError
        finally:
            await owner.aclose(preserve_error=True)

    waiter = asyncio.create_task(close_during_failure())
    try:
        await asyncio.wait_for(source.entered.wait(), COMPLETION_WATCHDOG)
        waiter.cancel("caller cancelled cleanup wait")
        with pytest.raises(asyncio.CancelledError, match="caller cancelled cleanup wait"):
            await waiter
        assert source.finished.is_set() is False
    finally:
        source.release.set()
        await owner.aclose()
    assert source.calls == 1
    assert source.finished.is_set()
