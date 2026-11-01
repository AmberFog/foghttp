import asyncio
from dataclasses import replace
from functools import partial

import pytest

from foghttp._multipart.cleanup import MultipartFileCleanup
from foghttp._multipart.models import MultipartFile
from foghttp._upload_body import cleanup, cleanup_owner
from foghttp._upload_body.thread_bridge import start_daemon_worker
from foghttp.errors import LifecycleError

from .cleanup_actions import wait_cleanup_count
from .constants import COMPLETION_WATCHDOG
from .iterator_sources import AsyncIteratorFactory, FailingIteratorSource, SyncCloseIterator, SyncIteratorFactory
from .sources import SyncCloseGate


def test_direct_multipart_iterator_creation_error_returns_capacity_and_keeps_source_open(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    failure = GeneratorExit("iterator creation interrupted")
    source = FailingIteratorSource(failure)
    owner = MultipartFileCleanup(_caller_owned_file(source))

    with pytest.raises(GeneratorExit) as observed:
        owner.create_iterator(partial(iter, source), source)

    assert observed.value is failure
    assert source.iteration_calls == 1
    assert source.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    recovery = SyncCloseGate(blocked=False)
    recovered = cleanup.UploadSourceCleanup(recovery, reservation=isolated_cleanup_owner.reserve(1))
    recovered.close()
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_sync_multipart_late_iterator_cleanup_retains_capacity_until_actual_close(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncIteratorFactory()
    owner = MultipartFileCleanup(_caller_owned_file(source))
    created = start_daemon_worker(partial(owner.create_iterator, partial(iter, source), source))
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        owner.close()
        source.release.set()
        assert created.result(timeout=COMPLETION_WATCHDOG) is source.iterator
        assert source.iterator.entered.wait(COMPLETION_WATCHDOG)
        owner.close()
        assert source.close_calls == 0
        assert source.iterator.calls == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert isolated_cleanup_owner.snapshot()["active"] == 1
    finally:
        source.release.set()
        source.iterator.release.set()
        created.result(timeout=COMPLETION_WATCHDOG)
        completion = owner.start_sync_cleanup()
        assert completion is not None
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert source.iterator.calls == 1
    assert source.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_async_multipart_late_iterator_cleanup_retains_capacity_on_originating_loop(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = AsyncIteratorFactory()
    owner = MultipartFileCleanup(_caller_owned_file(source, async_source=True))

    def close_during_creation() -> None:
        if not source.entered.wait(COMPLETION_WATCHDOG):
            message = "async iterator creation did not start"
            raise RuntimeError(message)
        try:
            owner.close()
        finally:
            source.release.set()

    closer = start_daemon_worker(close_during_creation)
    try:
        assert owner.create_iterator(partial(aiter, source), source) is source.iterator
        await asyncio.wait_for(source.iterator.entered.wait(), COMPLETION_WATCHDOG)
        closer.result(timeout=COMPLETION_WATCHDOG)
        await owner.aclose()
        assert source.iterator.calls == 1
        assert source.close_calls == 0
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert isolated_cleanup_owner.snapshot()["active"] == 1
    finally:
        source.release.set()
        source.iterator.release.set()
        await owner.aclose()
        await wait_cleanup_count(isolated_cleanup_owner, "reserved", 0)
    assert source.iterator.calls == 1
    assert source.close_calls == 0
    assert source.iterator.finished.is_set()


def _caller_owned_file(source: object, *, async_source: bool = False) -> MultipartFile:
    return MultipartFile(
        name="file",
        filename="payload.bin",
        content=source,
        content_type="application/octet-stream",
        content_length=None,
        replayable=False,
        async_source=async_source,
    )


def test_closed_multipart_owner_refuses_iterator_creation_and_fresh_owner_recovers(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncIteratorFactory()
    owner = MultipartFileCleanup(_caller_owned_file(source))
    owner.close()

    with pytest.raises(LifecycleError, match="multipart upload is closed"):
        owner.create_iterator(partial(iter, source), source)

    assert source.entered.is_set() is False
    assert source.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    source.release.set()
    source.iterator.release.set()
    recovered = MultipartFileCleanup(_caller_owned_file(source))
    assert recovered.create_iterator(partial(iter, source), source) is source.iterator
    recovered.close()
    assert source.iterator.calls == 1
    assert source.close_calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_owned_multipart_self_iterator_closes_once_without_distinct_iterator_charge(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncCloseIterator(blocked=False)
    file = replace(_caller_owned_file(source), close_source=True)
    owner = MultipartFileCleanup(file)

    assert owner.create_iterator(partial(iter, source), source) is source

    assert isolated_cleanup_owner.snapshot()["reserved"] == 1
    owner.close()
    owner.close()
    assert source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
