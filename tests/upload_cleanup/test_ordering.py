import asyncio
from concurrent.futures import CancelledError, Future
import threading
from unittest.mock import Mock

import pytest

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp._upload_body.attempt import wait_sync_cleanups

from .cleanup_actions import finish_sync_cleanups, wait_sync_event
from .constants import CHAIN_OBLIGATIONS, COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, FalseyCleanupError, SyncCloseGate


def test_sync_iterator_predecessor_retains_both_cleanup_obligations(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)
    completions: list[Future[None]] = []
    try:
        completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)
        assert completion is not None
        completions.append(completion)
        assert iterator.entered.wait(COMPLETION_WATCHDOG)

        assert source.calls == 0
        assert completion.done() is False
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        finish_sync_cleanups([iterator, source], completions)

    assert iterator.calls == 1
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


async def test_cancelled_waiter_does_not_advance_sync_cleanup_chain(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)
    completion = source_cleanup.start_async_cleanup(after=iterator_cleanup)
    assert completion is not None
    try:
        assert await wait_sync_event(iterator.entered)
        waiter = asyncio.create_task(source_cleanup.aclose(after=iterator_cleanup))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        iterator.release.set()
        await asyncio.wait_for(asyncio.shield(completion), COMPLETION_WATCHDOG)

    assert iterator.finished.is_set() is True
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


def test_loop_shutdown_and_switch_retain_actual_sync_predecessor_completion(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)

    async def close_in_loop() -> None:
        await source_cleanup.aclose(after=iterator_cleanup)

    try:
        asyncio.run(close_in_loop())
        assert iterator.entered.wait(COMPLETION_WATCHDOG)
        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS

        asyncio.run(close_in_loop())

        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        iterator.release.set()
        completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)
        assert completion is not None
        completion.result(timeout=COMPLETION_WATCHDOG)

    assert iterator.finished.is_set() is True
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        GeneratorExit("iterator cleanup control failure"),
        BaseExceptionGroup("iterator cleanup failures", [ValueError("ordinary failure"), GeneratorExit("control")]),
    ],
)
def test_predecessor_control_error_still_closes_source_and_releases_chain(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    failure: BaseException,
) -> None:
    iterator = SyncCloseGate(blocked=False, error=failure)
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)

    completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)

    assert completion is not None
    with pytest.raises(type(failure)) as observed:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert observed.value is failure
    assert iterator.calls == 1
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


def test_close_preserves_a_falsey_iterator_error_when_the_source_also_fails(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    failure = FalseyCleanupError("iterator cleanup control failure")
    iterator = SyncCloseGate(blocked=False, error=failure)
    source = SyncCloseGate(blocked=False, error=GeneratorExit("source cleanup control failure"))
    owner = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    owner.iteration.track(iterator)

    owner.start_sync_cleanup()
    assert owner.completion.exception(timeout=COMPLETION_WATCHDOG) is failure
    with pytest.raises(FalseyCleanupError) as caught:
        owner.close()
    assert caught.value is failure
    assert iterator.calls == source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_async_cleanup_preserves_the_predecessor_failure_when_its_inspection_can_interrupt_the_loop(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = isolated_cleanup_owner.reserve(1)
    original_failure = ValueError("iterator failed")
    iterator = SyncCloseGate(blocked=False, error=original_failure)
    receipt = predecessor.submit_sync(iterator.close)
    assert receipt.exception(timeout=COMPLETION_WATCHDOG) is original_failure
    read_exception = receipt.exception
    loop_thread = threading.get_ident()

    def inspect_predecessor(timeout: float | None = None) -> BaseException | None:
        if threading.get_ident() == loop_thread:
            raise GeneratorExit
        return read_exception(timeout)

    monkeypatch.setattr(receipt, "exception", inspect_predecessor)
    source = AsyncCloseGate()
    source.release.set()
    completion = isolated_cleanup_owner.reserve(1).submit_async(source.aclose, after=receipt)
    waiter = asyncio.wrap_future(completion)
    done, _pending = await asyncio.wait((waiter,), timeout=COMPLETION_WATCHDOG)
    assert waiter in done
    assert waiter.exception() is original_failure
    assert iterator.calls == source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_cancelled_predecessor_still_closes_the_source_and_releases_its_reservation(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    predecessor: Future[None] = Future()
    source = SyncCloseGate(blocked=False)
    completion = isolated_cleanup_owner.reserve(1).submit_sync(source.close, after=predecessor)
    assert predecessor.cancel()
    with pytest.raises(CancelledError):
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_interrupted_worker_start_retains_iterator_and_source_in_order(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    owner = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    owner.iteration.track(iterator)
    signal = KeyboardInterrupt()

    with monkeypatch.context() as rejected:
        rejected.setattr(threading.Thread, "start", Mock(side_effect=signal))
        with pytest.raises(KeyboardInterrupt) as caught:
            owner.start_sync_cleanup()
    assert caught.value is signal
    try:
        isolated_cleanup_owner.retry()
        assert iterator.entered.wait(COMPLETION_WATCHDOG)
        assert source.calls == 0
        assert owner.completion.done() is False
    finally:
        iterator.release.set()
    owner.completion.result(timeout=COMPLETION_WATCHDOG)
    assert iterator.calls == source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_interrupted_batch_start_keeps_all_sources_owned(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [SyncCloseGate(blocked=False), SyncCloseGate(blocked=False)]
    owners = [cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1)) for source in sources]
    signal = KeyboardInterrupt()
    with monkeypatch.context() as rejected:
        rejected.setattr(threading.Thread, "start", Mock(side_effect=signal))
        with pytest.raises(KeyboardInterrupt) as caught:
            wait_sync_cleanups(owners)

    assert caught.value is signal
    isolated_cleanup_owner.retry()
    for owner in owners:
        owner.completion.result(timeout=COMPLETION_WATCHDOG)
    assert [source.calls for source in sources] == [1, 1]
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
