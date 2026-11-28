import asyncio
import threading

import pytest

from foghttp._multipart.cleanup import MultipartFileCleanup
from foghttp._multipart.models import MultipartFile, MultipartPayload
from foghttp._multipart.stream import AsyncMultipartStream, MultipartStream
from foghttp._upload_body.cleanup import UploadSourceCleanup
from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import CHAIN_OBLIGATIONS, COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


def _payload(*parts: object, asynchronous: bool) -> MultipartPayload:
    files = tuple(
        MultipartFile(
            "file",
            "body",
            part,
            "application/octet-stream",
            None,
            replayable=False,
            async_source=asynchronous,
            close_source=True,
        )
        for part in parts
    )
    return MultipartPayload("boundary", (), files)


def test_sync_multipart_parent_waits_for_part_without_occupying_its_only_worker(
    isolated_cleanup_owner: CleanupOwner,
) -> None:
    failure = GeneratorExit("late multipart failure")
    part = SyncCloseGate(error=failure)
    owner = UploadSourceCleanup(MultipartStream(_payload(part, asynchronous=False)))
    completion = owner.start_sync_cleanup()
    assert completion is not None
    try:
        assert part.entered.wait(COMPLETION_WATCHDOG)
        assert owner.start_sync_cleanup() is completion
        assert completion.done() is False
        assert isolated_cleanup_owner.snapshot()["active"] == 1
        assert isolated_cleanup_owner.snapshot()["pending"] == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        part.release.set()

    with pytest.raises(GeneratorExit) as caught:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert caught.value is failure
    assert part.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_async_multipart_parent_waits_for_part_without_occupying_its_only_slot(
    isolated_cleanup_owner: CleanupOwner,
) -> None:
    part = AsyncCloseGate()
    owner = UploadSourceCleanup(AsyncMultipartStream(_payload(part, asynchronous=True)))
    waiter = owner.start_async_cleanup()
    assert waiter is not None
    try:
        await asyncio.wait_for(part.entered.wait(), COMPLETION_WATCHDOG)
        assert owner.start_async_cleanup() is waiter
        assert owner.completion.done() is False
        assert isolated_cleanup_owner.snapshot()["active"] == 1
        assert isolated_cleanup_owner.snapshot()["pending"] == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == CHAIN_OBLIGATIONS
        assert waiter.cancel()
    finally:
        part.release.set()

    await asyncio.wait_for(owner.aclose(bounded=False), COMPLETION_WATCHDOG)
    assert part.finished.is_set()
    assert part.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_queued_sync_multipart_cleanup_outlives_the_async_request_loop(isolated_cleanup_owner: CleanupOwner) -> None:
    gate = SyncCloseGate()
    blocker = UploadSourceCleanup(gate, reservation=isolated_cleanup_owner.reserve(1))
    running = blocker.start_sync_cleanup()
    assert running is not None
    part = SyncCloseGate(blocked=False)
    stream = MultipartStream(_payload(part, asynchronous=False))
    owner = UploadSourceCleanup(stream, reservation=isolated_cleanup_owner.reserve(1))

    async def start_on_request_loop() -> None:
        assert owner.start_async_cleanup() is not None
        assert owner.completion.done() is False

    try:
        assert gate.entered.wait(COMPLETION_WATCHDOG)
        asyncio.run(start_on_request_loop())
    finally:
        gate.release.set()
    running.result(timeout=COMPLETION_WATCHDOG)
    owner.completion.result(timeout=COMPLETION_WATCHDOG)
    assert part.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


def test_multipart_reports_first_part_error_after_all_parts_finish() -> None:
    first_error = GeneratorExit("first part")
    first = SyncCloseGate(error=first_error)
    second = SyncCloseGate(error=GeneratorExit("second part"))
    payload = _payload(first, second, asynchronous=False)
    parts = tuple(MultipartFileCleanup(file) for file in payload.files)
    stream = MultipartStream(payload, cleanups=parts)
    owner = UploadSourceCleanup(stream)
    completion = owner.start_sync_cleanup()
    assert completion is not None

    try:
        assert first.entered.wait(COMPLETION_WATCHDOG)
        assert second.entered.wait(COMPLETION_WATCHDOG)
        second.release.set()
        completed_second = parts[1].start_sync_cleanup()
        assert completed_second is not None
        with pytest.raises(GeneratorExit, match="second part"):
            completed_second.result(timeout=COMPLETION_WATCHDOG)
        assert owner.completion.done() is False
    finally:
        second.release.set()
        first.release.set()

    with pytest.raises(GeneratorExit) as caught:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert caught.value is first_error
    assert first.calls == second.calls == 1


def test_multipart_worker_interruption_is_reported_after_all_parts_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = CleanupOwner(max_active=2, max_obligations=3)
    first, last = SyncCloseGate(blocked=False), SyncCloseGate()
    payload = _payload(first, last, asynchronous=False)
    parts = tuple(
        MultipartFileCleanup(file, source_cleanup=UploadSourceCleanup(file.content, reservation=scheduler.reserve(1)))
        for file in payload.files
    )
    outer = UploadSourceCleanup(MultipartStream(payload, cleanups=parts), reservation=scheduler.reserve(1))
    caller = threading.current_thread()
    original_start = threading.Thread.start
    interruption = KeyboardInterrupt()

    def reject_additional_worker(worker: threading.Thread) -> None:
        if threading.current_thread() is not caller:
            raise interruption
        original_start(worker)

    monkeypatch.setattr(threading.Thread, "start", reject_additional_worker)
    try:
        completion = outer.start_sync_cleanup()
        assert completion is not None
        assert last.entered.wait(COMPLETION_WATCHDOG)
        assert first.finished.is_set()
        assert completion.done() is False
    finally:
        last.release.set()
    with pytest.raises(KeyboardInterrupt) as caught:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert caught.value is interruption
    assert first.calls == last.calls == 1
    assert scheduler.snapshot()["reserved"] == 0
